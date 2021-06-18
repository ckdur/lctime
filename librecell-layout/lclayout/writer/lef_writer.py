#
# Copyright 2019-2020 Thomas Kramer.
#
# This source describes Open Hardware and is licensed under the CERN-OHL-S v2.
#
# You may redistribute and modify this documentation and make products using it
# under the terms of the CERN-OHL-S v2 (https:/cern.ch/cern-ohl).
# This documentation is distributed WITHOUT ANY EXPRESS OR IMPLIED WARRANTY,
# INCLUDING OF MERCHANTABILITY, SATISFACTORY QUALITY AND FITNESS FOR A PARTICULAR PURPOSE.
# Please see the CERN-OHL-S v2 for applicable conditions.
#
# Source location: https://codeberg.org/tok/librecell
#
import logging
import time
from typing import Dict, List, Tuple, Optional
from klayout import db
import os

from .writer import Writer, remap_layers
from ..layout import layers
from ..lef import types as lef

logger = logging.getLogger(__name__)


def _decompose_region(region: db.Region, ignore_non_rectilinear: bool = False) -> List[db.Box]:
    """
    Decompose a `db.Region` of multiple `db.Polygon`s into non-overlapping rectangles (`db.Box`).
    :param region:
    :param ignore_non_rectilinear: If set to `True` then non-rectilinear polygons are skipped.
    :return: Returns the list of rectangles.
    """
    trapezoids = region.decompose_trapezoids_to_region()
    # logger.debug("Number of trapezoids: {}".format(trapezoids.size()))
    rectangles = []
    for polygon in trapezoids.each():
        box = polygon.bbox()

        if db.Polygon(box) != polygon:
            msg = "Cannot decompose into rectangles. Something is not rectilinear!"
            if not ignore_non_rectilinear:
                logger.error(msg)
                assert False, msg
            else:
                logger.warning(msg)

        rectangles.append(box)
    return rectangles


def region_to_geometries(region: db.Region, f: float, use_rectangles_only: bool = True) -> List:
    """
    Convert a region into a list of LEF geometries.
    :param use_rectangles_only: Decompose all polygons into rectangles.
    :param region:
    :param f: Scale the coordinates by this factor.
    :return:
    """
    region.merge()
    if use_rectangles_only:
        # Decompose into rectangles.
        boxes = _decompose_region(region)
        region = db.Region()
        region.insert(boxes)

    geometries = []
    for p in region.each():
        polygon = p.to_simple_polygon()

        box = polygon.bbox()
        is_box = db.SimplePolygon(box) == polygon

        if is_box:
            rect = lef.Rect((box.p1.x * f, box.p1.y * f), (box.p2.x * f, box.p2.y * f))
            geometries.append(rect)
        else:
            # Port is a polygon
            # Convert `db.Point`s into LEF points.
            points = [(p.x * f, p.y * f) for p in polygon.each_point()]
            poly = lef.Polygon(points)
            geometries.append(poly)
    return geometries


def generate_lef_macro(layout: db.Layout,
                       output_map: Dict[str, str],
                       obstruction_layers: List[str],
                       cell_name: str,
                       pin_geometries: Dict[str, List[Tuple[str, db.Shape]]],
                       pin_direction: Dict[str, lef.Direction],
                       pin_use: Dict[str, lef.Use],
                       site: str = "CORE",
                       scaling_factor: float = 1,
                       use_rectangles_only: bool = False,
                       ) -> lef.Macro:
    """
    Assemble a LEF MACRO structure containing the pin shapes.
    :param obstruction_layers: List of original layer names that should be output as obstructions.
    :param site: SITE name. Default is 'CORE'.
    :param cell_name: Name of the cell as it will appear in the LEF file.
    :param pin_geometries: A dictionary mapping pin names to geometries: Dict[pin name, List[(layer name, klayout Shape)]]
    :param pin_direction:
    :param pin_use: Pin USE for each pin name. 'SIGNAL' will be taken as a default.
    :param use_rectangles_only: Decompose all polygons into rectangles. Non-rectilinear shapes are dropped.
    :return: Returns a `lef.Macro` object containing the pin information of the cell.

    # TODO: FOREIGN statement (reference to GDS)
    """

    logger.debug("Generate LEF MACRO structure for {}.".format(cell_name))
    logger.debug(f"Scaling factor = {scaling_factor}.")

    f = scaling_factor

    pins = []
    # Create LEF Pin objects containing geometry information of the pins.
    for pin_name, ports in pin_geometries.items():

        pin_layers = []

        for layer_name, shape in ports:
            # Convert all non-regions into a region
            region = db.Region()
            region.insert(shape)

            geometries = region_to_geometries(region, f)

            output_layer_name = output_map.get(layer_name, layer_name)
            pin_layers.append((lef.Layer(output_layer_name), geometries))

        port = lef.Port(CLASS=lef.Class.CORE,
                        geometries=pin_layers)

        # if pin_name not in pin_direction:
        #     msg = "I/O direction of pin '{}' is not defined.".format(pin_name)
        #     logger.error(msg)
        #     assert False, msg
        #
        # if pin_name not in pin_use:
        #     msg = "Use of pin '{}' is not defined. Must be one of (CLK, SIGNAL, POWER, ...)".format(pin_name)
        #     logger.error(msg)
        #     assert False, msg

        pin = lef.Pin(pin_name=pin_name,
                      direction=lef.Direction.INOUT,  # TODO: find direction
                      use=pin_use.get(pin_name, lef.Use.SIGNAL),
                      shape=lef.Shape.ABUTMENT,
                      port=port,
                      property={},
                      )
        pins.append(pin)

    # Store all routing shapes as 'obstructions'.
    cell_id = layout.cell_by_name(cell_name)
    cell = layout.cell(cell_id)
    assert isinstance(cell, db.Cell)
    layer_infos = list(layout.layer_infos())
    layer_infos = {i.name: i for i in layer_infos}
    obstructions = []
    for obstruction_layer in obstruction_layers:
        layer_info = layer_infos[obstruction_layer]
        assert layer_info is not None
        assert isinstance(layer_info, db.LayerInfo)
        shapes = cell.shapes(layout.layer(layer_info))

        region = db.Region(shapes)
        geometries = region_to_geometries(region, f)
        obstruction_layer_name = output_map.get(obstruction_layer, obstruction_layer)
        obs = lef.Obstruction(lef.Layer(obstruction_layer_name), geometries)
        obstructions.append(obs)

    # Find size of the abutment box.
    bbox = db.Region(cell.shapes(layout.layer(layer_infos[layers.l_abutment_box]))).bbox()
    cell_size = (bbox.width(), bbox.height())

    macro = lef.Macro(
        name=cell_name,
        macro_class=lef.MacroClass.CORE,
        foreign=lef.Foreign(cell_name, lef.Point(0, 0)),
        size=(cell_size[0]*f, cell_size[1]*f),
        origin=lef.Point(0, 0),
        symmetry={lef.Symmetry.X, lef.Symmetry.Y, lef.Symmetry.R90},
        site=site,
        pins=pins,
        obstructions=obstructions
    )

    return macro


class LefWriter(Writer):

    def __init__(self,
                 output_map: Dict[str, str],
                 obstruction_layers: List[str],
                 site: str = "CORE",
                 db_unit: float = 1e-6,
                 use_rectangles_only: bool = False):
        """
        :param output_map: Mapping from lclayout layer names to output layer names.
        :param obstruction_layers: List of layers that should be output as obstructions (requires the internal layer names).
        :param site: SITE name.
        :param db_unit: Database unit in meters. Default is 1um (1e-6 m)
        :param use_rectangles_only: Convert all polygons into rectangles. Non-rectilinear shapes are dropped.
        """
        self.obstruction_layers = obstruction_layers
        self.db_unit = db_unit
        self.output_map = output_map
        self.scaling_factor = 1
        self.use_rectangles_only = use_rectangles_only
        self.site = site

    def write_layout(self,
                     layout: db.Layout,
                     pin_geometries: Dict[str, List[Tuple[str, db.Shape]]],
                     top_cell: db.Cell,
                     output_dir: str,
                     ) -> None:
        # # Re-map layers
        # layout = remap_layers(layout, self.output_map)

        # Compute correct scaling factor.
        # klayout expects dbu to be in µm, the tech file takes it in meters.
        logger.debug(f"LEF db_unit = {self.db_unit} [m]")
        scaling_factor = self.db_unit / (layout.dbu)
        scaling_factor *= self.scaling_factor  # Allow to make corrections from the tech file.

        # Write LEF
        # Create and populate LEF Macro data structure.
        # TODO: pass correct DIRECTION

        pin_use = {
            top_cell.property("gnd_net"): lef.Use.POWER,
            top_cell.property("supply_net"): lef.Use.POWER,
        }

        lef_macro = generate_lef_macro(layout,
                                       self.output_map,
                                       self.obstruction_layers,
                                       top_cell.name,
                                       pin_geometries=pin_geometries,
                                       pin_use=pin_use,
                                       pin_direction=None,
                                       site=self.site,
                                       scaling_factor=scaling_factor,
                                       use_rectangles_only=self.use_rectangles_only)

        # Write LEF
        lef_file_name = "{}.lef".format(top_cell.name)
        lef_output_path = os.path.join(output_dir, lef_file_name)

        with open(lef_output_path, "w") as f:
            logger.info("Write LEF: {}".format(lef_output_path))
            f.write(lef.lef_format(lef_macro))
