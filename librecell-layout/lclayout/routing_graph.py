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
import networkx as nx
import klayout.db as db
from itertools import count, product
from collections import defaultdict

from .layout.grid_helpers import *
from .layout.geometry_helpers import *
from .layout.grid import Grid2D
from .layout.layers import *
from .layout.transistor import TransistorLayout
from .data_types import Transistor
from . import tech_util

from typing import Any, Dict, List, Tuple, Iterable, Set
import logging

logger = logging.getLogger(__name__)


def create_routing_graph_base(grid: Grid2D, tech) -> nx.Graph:
    """ Construct the full mesh of the routing graph.
    :param grid: grid points
    :param tech: module containing technology information
    :return: nx.Graph
    """
    logging.debug('Create routing graph.')

    # Create routing graph.

    # Create nodes and vias.
    G = nx.Graph()

    # Keep track of missing weights to output a log warning.
    missing_via_weights = set()

    # Create nodes on routing layers.
    for layer, directions in tech.routing_layers.items():
        for p in grid:
            n = layer, p
            G.add_node(n)

    # Create via edges.
    for l1, l2, data in via_layers.edges(data=True):
        via_layer = data['layer']
        for p in grid:
            n1 = (l1, p)
            n2 = (l2, p)

            weight = tech.via_weights.get((l1, l2))
            if weight is None:
                weight = tech.via_weights.get((l2, l1))
                if weight is None:
                    missing_via_weights.add((l1, l2))
                    weight = 0

            multi_via = tech.multi_via.get((l1, l2))
            if multi_via is None:
                multi_via = tech.multi_via.get((l2, l1), 1)

            # Create edge: n1 -- n2
            G.add_edge(n1, n2,
                       weight=weight,
                       multi_via=multi_via,
                       layer=via_layer
                       )

    for (l1, l2) in missing_via_weights:
        logger.warning(f"No via weight specified from layer '{l1}' to '{l2}'.")

    # Create intra layer routing edges.
    for layer, directions in tech.routing_layers.items():
        for p1 in grid:
            x1, y1 = p1
            x2 = x1 + tech.routing_grid_pitch_x
            y2 = y1 + tech.routing_grid_pitch_y

            # ID of the graph node.
            n = layer, p1

            # Horizontal edge.
            if 'h' in directions:
                n_right = layer, (x2, y1)
                if n_right in G.nodes:
                    weight = tech.weights_horizontal[layer] * abs(x2 - x1)
                    G.add_edge(n, n_right, weight=weight, orientation='h', layer=layer)

            # Vertical edge.
            if 'v' in directions:
                n_upper = layer, (x1, y2)
                if n_upper in G.nodes:
                    weight = tech.weights_vertical[layer] * abs(y2 - y1)
                    G.add_edge(n, n_upper, weight=weight, orientation='v', layer=layer)

    assert nx.is_connected(G)
    return G


def create_routing_graph_base_v2(xs: List[int], ys: List[int], tech) -> nx.Graph:
    """ Construct the full mesh of the routing graph.
    :param tech: module containing technology information
    :return: nx.Graph
    """
    logging.debug('Create routing graph.')

    # Create routing graph.

    # Create nodes and vias.
    G = nx.Graph()

    # Keep track of missing weights to output a log warning.
    missing_via_weights = set()

    # Create nodes on routing layers.
    for layer, directions in tech.routing_layers.items():
        for p in product(xs, ys):
            n = layer, p
            G.add_node(n)

    # Create via edges.
    for l1, l2, data in via_layers.edges(data=True):
        via_layer = data['layer']
        for p in product(xs, ys):
            n1 = (l1, p)
            n2 = (l2, p)

            weight = tech.via_weights.get((l1, l2))
            if weight is None:
                weight = tech.via_weights.get((l2, l1))
                if weight is None:
                    missing_via_weights.add((l1, l2))
                    weight = 0

            multi_via = tech.multi_via.get((l1, l2))
            if multi_via is None:
                multi_via = tech.multi_via.get((l2, l1), 1)

            # Create edge: n1 -- n2
            G.add_edge(n1, n2,
                       weight=weight,
                       multi_via=multi_via,
                       layer=via_layer
                       )

    for (l1, l2) in missing_via_weights:
        logger.warning(f"No via weight specified from layer '{l1}' to '{l2}'.")

    # Create intra layer routing edges.
    for layer, directions in tech.routing_layers.items():

        # Horizontal edge.
        if 'h' in directions:
            for x1, x2 in zip(xs, xs[1:]):
                for y1 in ys:
                    p1 = x1, y1

                    # ID of the graph node.
                    n = layer, p1

                    n_right = layer, (x2, y1)
                    if n_right in G.nodes:
                        weight = tech.weights_horizontal[layer] * abs(x2 - x1)
                        G.add_edge(n, n_right, weight=weight, orientation='h', layer=layer)

        # Vertical edge.
        if 'v' in directions:
            for x1 in xs:
                for y1, y2 in zip(ys, ys[1:]):
                    p1 = x1, y1

                    # ID of the graph node.
                    n = layer, p1

                    n_upper = layer, (x1, y2)
                    if n_upper in G.nodes:
                        weight = tech.weights_vertical[layer] * abs(y2 - y1)
                        G.add_edge(n, n_upper, weight=weight, orientation='v', layer=layer)

    assert nx.is_connected(G)
    return G


def _get_routing_node_locations_per_layer(g: nx.Graph) -> Dict[Any, Set[Tuple[int, int]]]:
    """ For each layer extract the positions of the routing nodes.

    :param g: Routing graph.
    :return: Dict[layer name, set of (x,y) coordinates of routing nodes]
    """
    # Dict that will contain for each layer the node coordinates that can be used for routing.
    routing_nodes = defaultdict(set)
    # Populate `routing_nodes`
    for e in g.edges:
        (l1, p1), (l2, p2) = e
        routing_nodes[l1].add(p1)
        routing_nodes[l2].add(p2)

    return routing_nodes


def remove_illegal_routing_edges(graph: nx.Graph, shapes: Dict[Any, db.Shapes], tech) -> None:
    """ Remove nodes and edges from  G that would conflict
    with predefined `shapes` as well as with shapes of neighbour cells.
    :param graph: routing graph.
    :param shapes: Dict[layer name, db.Shapes]
    :param tech: module containing technology information
    :return: Dict[layer name, List[Node]]
    """

    # Build a spacing rule graph by mapping the minimal spacing between layer a and layer b to an edge
    # a-b in the graph with weight=min_spacing.
    spacing_graph = tech_util.spacing_graph(tech.min_spacing)

    # Get a dict mapping layer names to db.Regions
    regions = {l: db.Region(s) for l, s in shapes.items()}

    # Ensure that no spacing rules are violated when cells are abutted together.
    # This is done by filling all layers around the cell.
    for via_layer, region in regions.items():
        if via_layer in spacing_graph:
            # Find the largest min-spacing to any other layer.
            largest_min_spacing = max((spacing_graph[via_layer][other]['min_spacing'] for other in spacing_graph[via_layer]))
            half_spacing = largest_min_spacing // 2  # Spacing to the cell outline.

            cell_region = db.Region()
            cell_region.insert(shapes[l_abutment_box])
            cell_region += region

            # Create the surrounding shape around the cell by taking the bounding box and enlarging it slightly.
            surrounding = db.Region()
            surrounding.insert(cell_region.bbox())
            surrounding.size(10 + half_spacing)

            # Create a hole into the surrounding. The hole marks the space allowed for routing.
            # The hole is enlarged by the half spacing because it is assumed that neighbour cells
            # will also follow the half-spacing rule.
            surrounding -= cell_region.sized(half_spacing)

            # Insert the surrounding shapes.
            region.insert(surrounding)

    illegal_edges = set()
    # For each edge in the graph check if it conflicts with an existing shape.
    # Remember the edge if it is in conflict.
    for e in graph.edges:
        (l1, p1), (l2, p2) = e
        is_via = l1 != l2  # TODO: Vias are now separate nodes.

        if not is_via:
            via_layer = l1
            other_layers = spacing_graph[via_layer]
            for other_layer in other_layers:
                if other_layer != via_layer:
                    min_spacing = spacing_graph[via_layer][other_layer]['min_spacing']
                    wire_width_half = (tech.wire_width.get(via_layer, 0) + 1) // 2
                    margin = wire_width_half + min_spacing
                    # TODO: treat horizontal and vertical lines differently if they don't have the same wire width.
                    region = regions[other_layer]
                    is_illegal_edge = interacts(p1, region, margin) or interacts(p2, region, margin)

                    if is_illegal_edge:
                        illegal_edges.add(e)
        else:
            assert p1 == p2, "End point coordinates of a via edge must match."
            via_layer = via_layers[l1][l2]['layer']

            if via_layer in spacing_graph:
                other_layers = spacing_graph[via_layer]
                for other_layer in other_layers:
                    if other_layer != via_layer:
                        if via_layer in spacing_graph and other_layer in spacing_graph:
                            min_spacing = spacing_graph[via_layer][other_layer]['min_spacing']
                            via_width_half = (tech.via_size[via_layer] + 1) // 2
                            margin = via_width_half + min_spacing
                            region = regions[other_layer]
                            is_illegal_edge = interacts(p1, region, margin)

                            if is_illegal_edge:
                                illegal_edges.add(e)

    # Now remove all edges from G that are in conflict with existing shapes.
    graph.remove_edges_from(illegal_edges)

    # Remove unconnected nodes.
    unconnected = set()
    for n in graph:
        d = nx.degree(graph, n)
        if d < 1:
            unconnected.add(n)
    graph.remove_nodes_from(unconnected)


def add_via_nodes(graph: nx.Graph, tech) -> nx.Graph:
    """
    Split all inter-layer edges by inserting a node which represents the via.
    This is used to define conflicts between vias and metal layers and allows
    to model the conflicts that are caused by the via-enclosure.
    :param graph:
    :param tech:
    :return:
    """
    new_graph = nx.Graph()

    for a, b, data in graph.edges(data=True):
        via_layer = data['layer']
        weight = data.get('weight', 0)
        _, location = a  # Via location.
        via_node = via_layer, location

        new_data = data.copy()
        new_data['weight'] = weight / 2

        new_graph.add_edge(a, via_node, **new_data)
        new_graph.add_edge(via_node, b, **new_data)

    return new_graph


def remove_existing_routing_edges(G: nx.Graph, shapes: Dict[Any, db.Shapes], tech) -> None:
    """ Remove edges in G that are already routed by a shape in `shapes`.
    :param G: Routing graph to be modified.
    :param shapes: Dict[layer, db.Shapes]
    :param tech: module containing technology information
    :return: None
    """

    # Remove all routing edges that are inside existing shapes.
    # (They are already connected and cannot be used for routing).
    for l in tech.routing_layers.keys():
        r = db.Region(shapes[l])
        r.merge()
        edges = edges_inside(G, r, 1)
        for e in edges:
            (l1, _), (l2, _) = e
            if (l1, l2) == (l, l):
                G.remove_edge(*e)


def _extract_terminal_nodes_from_shape(routing_nodes: Dict[Any, Set[Tuple[int, int]]],
                                       layer: str,
                                       shape: db.Shape,
                                       tech) -> List[Tuple[int, int]]:
    """
    Get coordinates of routing nodes that lie inside the shape.
    :param graph:
    :param routing_nodes: Set of node coordinates per layer.
    :param layer:
    :param net_shape:
    :param tech:
    :return:
    """

    # Determine the maximum size of adjacent vias.
    possible_via_layers = [data['layer'] for _, _, data in via_layers.edges(layer, data=True)]
    assert len(possible_via_layers) > 0, f"No via layer is specified that connects to layer '{layer}'."
    enc = max((tech.minimum_enclosure.get((layer, via_layer), 0) for via_layer in possible_via_layers),
              default=0)
    max_via_size = max((tech.via_size[l] for l in possible_via_layers))

    # TODO: How to convert db.Shape into db.Region in a clean way???

    if isinstance(shape, db.Shape):
        s = db.Shapes()
        s.insert(shape)
        terminal_region = db.Region(s)
    else:
        terminal_region = db.Region()
        terminal_region.insert(shape)

    if layer in tech.routing_layers:
        # On routing layers enclosure can be added, so nodes are not required to be properly enclosed.
        d = 1
        routing_terminals = interacting(routing_nodes[layer], terminal_region, d)
    else:
        # A routing node must be properly enclosed to be used.
        d = enc + max_via_size // 2
        routing_terminals = inside(routing_nodes[layer], terminal_region, d)

    return routing_terminals


def extract_terminal_nodes_by_lvs(graph: nx.Graph,
                                  pin_shapes_by_net: Dict[str, List[List[Tuple[str, db.Polygon]]]],
                                  tech) -> List[Tuple[str, List]]:
    """
    Extract terminals by using the netlist extraction functionality of Klayout.
    Routing nodes that are already connected by existing routing are put into a single terminal.
    :param graph:
    :param pin_shapes_by_net:
    :param tech:
    :return: A list of the form [(net name, [terminal1_node1, terminal1_node1, ...]), ...]
    """
    routing_nodes = _get_routing_node_locations_per_layer(graph)

    # Create a list of terminal areas: [(net, layer, [terminal, ...]), ...]
    terminals_by_net = []
    for net, pins in pin_shapes_by_net.items():
        for pin in pins:
            # Find all routing nodes that belong to this pin.
            # (They should already be connected together.)
            pin_nodes = []
            for terminal_shape in pin:
                # Get all nodes of this terminal shape. Append them to the nodes of the pin.
                layer, polygon = terminal_shape

                if layer in routing_nodes:  # Skip via layers.
                    assert isinstance(polygon, db.Polygon)

                    nodes = _extract_terminal_nodes_from_shape(routing_nodes,
                                                               layer,
                                                               polygon,
                                                               tech)

                    # Don't use terminals for normal routing

                    routing_nodes[layer] -= set(nodes)
                    # TODO: need to be removed from G also. Better: construct edges in G afterwards.

                    pin_nodes.extend(((layer, t) for t in nodes))
            if pin_nodes:
                terminals_by_net.append((net, pin_nodes))

    return terminals_by_net


def extract_terminal_nodes(graph: nx.Graph,
                           shapes: Dict[str, db.Shapes],
                           tech) -> List[Tuple[str, List]]:
    """ Get terminal nodes for each net.
    Terminal nodes are extracted from the shapes on the layer and their 'net' property.
    :param graph: Routing graph.
    :param net_regions: Regions that are connected to a net: Dict[net, Dict[layer, db.Region]]
    :param tech: module containing technology information
    :return: list of terminals: [(net, [(layer, terminal coordinates), ...]), ...]
    """

    routing_nodes = _get_routing_node_locations_per_layer(graph)

    # Create a list of terminal areas: [(net, layer, [terminal, ...]), ...]
    terminals_by_net = []
    for layer, _shapes in shapes.items():
        for net_shape in _shapes.each():
            net = net_shape.property('net')

            if net is not None:
                nodes = _extract_terminal_nodes_from_shape(routing_nodes,
                                                           layer,
                                                           net_shape,
                                                           tech)

                terminals_by_net.append((net, [(layer, t) for t in nodes]))
                # Don't use terminals for normal routing
                routing_nodes[layer] -= set(nodes)
                # TODO: need to be removed from G also. Better: construct edges in G afterwards.

    # Remove empty terminals.
    terminals_by_net = [(net, terms) for net, terms in terminals_by_net if terms]

    return terminals_by_net


#
# def embed_terminal_nodes(G: nx.Graph, terminals: Iterable[Tuple[str, str, Tuple[int, int]]], tech):
#     for net, layer, (x, y) in terminals:
#
#         logger.info(f"Terminal node {net} {layer} {(x, y)}")
#
#         # Insert terminal into G.
#         next_x = grid_round(x, tech.routing_grid_pitch_x, tech.grid_offset_x)
#
#         assert next_x == x, Exception("Terminal node not x-aligned.")
#
#         x_aligned_nodes = [(l, (_x, y)) for l, (_x, y) in G if l == layer and _x == x]
#
#         def dist(a, b):
#             _, (x1, y1) = a
#             _, (x2, y2) = b
#             return (x1 - x2) ** 2 + (y1 - y2) ** 2
#
#         if x_aligned_nodes:
#             neighbour_node = min(x_aligned_nodes, key=lambda n: dist(n, t))
#
#             # TODO: weight proportional to gate width?
#             G.add_edge(t, neighbour_node, weight=1000, wire_width=tech.gate_length)
#             coords.append((x, y))
#         else:
#             logger.debug(f"No neighbour node for terminal with net `{net}` of transistor {transistor.name}.")


def embed_transistor_terminal_nodes(G: nx.Graph,
                                    transistor_layouts: Dict[Transistor, TransistorLayout],
                                    tech) -> List[Tuple[str, List[Tuple[str, Tuple[int, int]]]]]:
    """ Embed the terminal nodes of a the transistors into the routing graph.
    Modifies `G` and `terminals_by_net`
    :param G: The routing graph.
    :param transistor_layouts: List[TransistorLayout]
    :param tech: module containing technology information
    :return: Returns terminal nodes as a list like List[(netname, [(layer, coordinate), ...])]
    """
    terminals_by_net = []
    # Connect terminal nodes of transistor gates in G.
    for transistor, t_layout in transistor_layouts.items():
        terminals = t_layout.terminal_nodes()
        for net, ts in terminals.items():
            coords = []  # Coordinates of inserted terminal nodes.
            layer = None
            for t in ts:
                layer, (x, y) = t

                # logger.debug(f"Terminal node {net} {layer} {t}")

                # Insert terminal into G.
                next_x = grid_round(x, tech.routing_grid_pitch_x, tech.grid_offset_x)

                assert next_x == x, Exception("Terminal node not x-aligned.")

                x_aligned_nodes = [(l, (_x, y)) for l, (_x, y) in G if l == layer and _x == x]

                def dist(a, b):
                    _, (x1, y1) = a
                    _, (x2, y2) = b
                    return (x1 - x2) ** 2 + (y1 - y2) ** 2

                if x_aligned_nodes:
                    neighbour_node = min(x_aligned_nodes, key=lambda n: dist(n, t))

                    # TODO: weight proportional to gate width?
                    G.add_edge(t, neighbour_node, weight=1000, wire_width=tech.gate_length)

                    assert layer is not None
                    coords.append((layer, (x, y)))
                else:
                    logger.debug(f"No neighbour node for terminal with net `{net}` of transistor {transistor.name}.")

            if coords:
                terminals_by_net.append((net, coords))

    return terminals_by_net


def create_virtual_terminal_nodes(G: nx.Graph,
                                  terminals_by_net: List[Tuple[str, List[Tuple[str, Tuple[int, int]]]]],
                                  io_pins: Iterable,
                                  tech):
    """ Create virtual terminal nodes for each net.
    :param G: The routing graph. Will be modified.
    :param terminals_by_net:
    :param io_pins: Names of the I/O nets.
    :param tech: module containing technology information
    :return: Returns a set of virtual terminal nodes: Dict[('virtual...', net, layer, id)]
    """

    # Extract all routing nodes for each layer.
    routing_nodes = _get_routing_node_locations_per_layer(G)

    # Create virtual graph nodes for each net terminal.
    virtual_terminal_nodes = defaultdict(list)
    cnt = count()

    for net, terminals in terminals_by_net:
        weight = 1000
        if len(terminals) > 0:

            virtual_net_terminal = ('virtual', net, next(cnt))
            virtual_terminal_nodes[net].append(virtual_net_terminal)

            for layer, p in terminals:
                n = layer, p
                assert n in G.nodes, "Node not present in graph: %s" % str(n)
                # High weight for virtual edge
                # TODO: High weight only for low-resistance layers.
                G.add_edge(virtual_net_terminal, n, weight=weight)

    cnt = count()
    # Create virtual nodes for I/O pins.
    for p in io_pins:
        virtual_net_terminal = ('virtual_pin', p, next(cnt))
        virtual_terminal_nodes[p].append(virtual_net_terminal)

        for p in routing_nodes[tech.pin_layer]:
            n = tech.pin_layer, p
            x, y = p
            assert n in G.nodes, "Node not present in graph: %s" % str(n)
            # A huge weight assures that the virtual node is not used as a worm hole for routing.
            weight = 10000000 + (y - tech.unit_cell_height // 2) // tech.routing_grid_pitch_y
            G.add_edge(virtual_net_terminal, n, weight=weight)

    return virtual_terminal_nodes
