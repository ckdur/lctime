from .graphrouter.graphrouter import GraphRouter
from .routing_graph import *
from . import tech_util
from .lvs import lvs
import networkx as nx
import numpy
import klayout.db as db
import itertools

def _draw_routing_tree(shapes: Dict[str, pya.Shapes],
                       G: nx.Graph,
                       signal_name: str,
                       rt: nx.Graph,
                       tech,
                       debug_routing_graph: bool = False):
    """ Draw a routing graph into a layout.
    :param shapes: Mapping from layer name to pya.Shapes object
    :param G: Full graph of routing grid
    :param signal_name: Name of the net.
    :param rt: Graph representing the wires
    :param tech: module containing technology information
    :param debug_routing_graph: Draw narrower wires for easier visual inspection
    :return:
    """

    def is_virtual_node(n):
        return n[0].startswith('virtual')

    def is_virtual_edge(e):
        return is_virtual_node(e[0]) or is_virtual_node(e[1])

    logger.debug("Drawing wires")

    # Loop through all edges of the routing tree and draw them individually.

    for a, b in rt.edges:
        if is_virtual_edge((a, b)):
            continue
        l1, (x1, y1) = a
        l2, (x2, y2) = b
        if l1 in tech.routing_layers and l2 in tech.routing_layers:
            data = G[a][b]

            if l1 == l2:
                # On the same layer -> wire

                w = data.get('wire_width', tech.wire_width[l1])

                ext = w // 2

                is_horizontal = y1 == y2 and x1 != x2

                if is_horizontal:
                    w = tech.wire_width_horizontal[l1]

                if debug_routing_graph:
                    w = min(tech.routing_grid_pitch_x, tech.routing_grid_pitch_y) // 16

                path = pya.Path([pya.Point(x1, y1), pya.Point(x2, y2)], w, ext, ext)
                s = shapes[l1].insert(path)
                s.set_property('net', signal_name)

            # else:
            #     # l1 != l1 -> this looks like a via
            #     assert x1 == x2
            #     assert y1 == y2
            #     # Draw via
            #     via_layer = via_layers[l1][l2]['layer']
            #     logger.debug('Draw via: {} ({}, {})'.format(via_layer, x1, y1))
            #
            #     via_width = tech.via_size[via_layer]
            #
            #     if debug_routing_graph:
            #         via_width = min(tech.routing_grid_pitch_x, tech.routing_grid_pitch_y) // 16
            #
            #     w = via_width // 2
            #     via = pya.Box(pya.Point(x1 - w, y1 - w),
            #                   pya.Point(x1 + w, y1 + w))
            #     via_shape = shapes[via_layer].insert(via)
            #     # via_shape.set_property('net', signal_name)
            #
            #     # Ensure minimum via enclosure.
            #     if not debug_routing_graph:
            #         for l in (l1, l2):
            #             # TODO: Check on which sides minimum enclosure is not yet satisfied by some wire.
            #
            #             neighbors = rt.neighbors((l, (x1, y1)))
            #             neighbors = [n for n in neighbors if n[0] == l]
            #
            #             w_ext = via_width // 2 + tech.minimum_enclosure.get((l, via_layer), 0)
            #             w_noext = via_width // 2
            #
            #             # Check on which sides the enclosure must be extended.
            #             # Some sides will already be covered by a routing wire.
            #             ext_right = w_ext
            #             ext_upper = w_ext
            #             ext_left = w_ext
            #             ext_lower = w_ext
            #             # TODO
            #             # for _, (n_x, n_y) in neighbors:
            #             #     if n_x == x1:
            #             #         if n_y < y1:
            #             #             ext_lower = w_noext
            #             #         if n_y > y1:
            #             #             ext_upper = w_noext
            #             #     if n_y == y1:
            #             #         if n_x < x1:
            #             #             ext_left = w_noext
            #             #         if n_x > x1:
            #             #             ext_right = w_noext
            #
            #             enc = pya.Box(
            #                 pya.Point(x1 - ext_left, y1 - ext_lower),
            #                 pya.Point(x1 + ext_right, y1 + ext_upper)
            #             )
            #             s = shapes[l].insert(enc)
            #             s.set_property('net', signal_name)

    # Create lookup-table from 'via layer name' to 'lower and upper metal layer name'.
    via_layer_names = set()
    for (a, b, data) in via_layers.edges(data=True):
        layer = data['layer']
        via_layer_names.add(layer)

    # Draw vias.
    for n in rt.nodes():

        if is_virtual_node(n):
            continue

        layer, location = n

        if layer in via_layer_names:

            neighbours = list(rt.neighbors(n))
            (l1, _), (l2, _) = neighbours

            via_layer = layer
            x1, y1 = location
            # logger.debug('Draw via: {} ({}, {})'.format(via_layer, x1, y1))

            via_width = tech.via_size[via_layer]

            if debug_routing_graph:
                via_width = min(tech.routing_grid_pitch_x, tech.routing_grid_pitch_y) // 16

            w = via_width // 2
            via = pya.Box(pya.Point(x1 - w, y1 - w),
                          pya.Point(x1 + w, y1 + w))
            via_shape = shapes[via_layer].insert(via)
            via_shape.set_property('net', signal_name)

            # Ensure minimum via enclosure.
            if not debug_routing_graph:
                for l in (l1, l2):
                    # TODO: Check on which sides minimum enclosure is not yet satisfied by some wire.

                    neighbors = rt.neighbors((l, (x1, y1)))
                    neighbors = [n for n in neighbors if n[0] == l]

                    w_ext = via_width // 2 + tech.minimum_enclosure.get((l, via_layer), 0)
                    w_noext = via_width // 2

                    # Check on which sides the enclosure must be extended.
                    # Some sides will already be covered by a routing wire.
                    ext_right = w_ext
                    ext_upper = w_ext
                    ext_left = w_ext
                    ext_lower = w_ext
                    # TODO
                    # for _, (n_x, n_y) in neighbors:
                    #     if n_x == x1:
                    #         if n_y < y1:
                    #             ext_lower = w_noext
                    #         if n_y > y1:
                    #             ext_upper = w_noext
                    #     if n_y == y1:
                    #         if n_x < x1:
                    #             ext_left = w_noext
                    #         if n_x > x1:
                    #             ext_right = w_noext

                    enc = pya.Box(
                        pya.Point(x1 - ext_left, y1 - ext_lower),
                        pya.Point(x1 + ext_right, y1 + ext_upper)
                    )
                    s = shapes[l].insert(enc)
                    s.set_property('net', signal_name)


class DefaultRouter():

    def __init__(self,
                 graph_router: GraphRouter,
                 tech,
                 debug_routing_graph: bool = False):
        self.tech = tech  # Technology data.
        self.debug_routing_graph = debug_routing_graph
        self.router = graph_router

        # Load spacing rules in form of a graph.
        self._spacing_graph = tech_util.spacing_graph(self.tech.min_spacing)

    def route(self, shapes: Dict[str, db.Shapes],
              io_pins: List[str],
              transistor_layouts: Dict[Transistor, TransistorLayout],
              routing_nets: Set[str] = None,
              routing_terminal_debug_layers: Dict[str, str] = None,
              top_cell: db.Cell = None
              ):
        """
        :param shapes:
        :param io_pins: Create accessible metal shapes for this nets.
        :param transistor_layouts:
        :param routing_terminal_debug_layers:
        :param routing_nets: Route this nets only. When left `None` all nets will be routed.
        :param top_cell: Layout cell where routes should be drawn.
        :return: Returns the routing trees for each signal.
        """
        routing_trees = self._06_route(shapes, io_pins, transistor_layouts,
                                       routing_nets,
                                       routing_terminal_debug_layers, top_cell)
        self._08_draw_routes(shapes, routing_trees)
        return routing_trees

    def _06_route(self, shapes: Dict[str, db.Shapes],
                  io_pins: List[str],
                  transistor_layouts: Dict[Transistor, TransistorLayout],
                  routing_nets: Set[str] = None,
                  routing_terminal_debug_layers: Dict[str, str] = None,
                  top_cell: db.Cell = None):
        """

        :param shapes:
        :param io_pins: Create accessible metal shapes for this nets.
        :param transistor_layouts:
        :param routing_terminal_debug_layers:
        :param routing_nets: Route this nets only. When left `None` all nets will be routed.
        :param top_cell: Layout cell where routes should be drawn.
        :return: Returns the routing trees for each signal.
        """
        # TODO: Move as much as possible of the grid construction into a router specific class.
        tech = self.tech

        cell_width = db.Region(shapes[l_abutment_box]).bbox().width()

        # Find all net names in the layout.
        all_net_names = {s.property('net') for _, _shapes in shapes.items() for s in _shapes.each()}
        if routing_nets is not None:
            all_net_names &= routing_nets
        all_net_names -= {None}

        # Transform the 'net' properties into text labels such that the LVS
        # algorithm picks the right net names.
        net_labels = []
        for layer_name, _shapes in shapes.items():
            for shape in _shapes.each():
                assert isinstance(shape, db.Shape)
                net_name = shape.property('net')
                if net_name is not None:
                    p = shape.polygon
                    assert isinstance(p, db.Polygon)

                    # Find a position which is clearly inside the polygon to place the label.
                    r = db.Region()
                    r.insert(p)
                    # Decompose into rectangles and pick a rectangle.
                    rects = r.decompose_trapezoids_to_region()
                    t = next(rects.each())
                    # Put the label in the center of the rectangle.
                    center = t.bbox().center()

                    label = db.Text(net_name, center.x, center.y)
                    net_labels.append((layer_name, label))

        for layer_name, label in net_labels:
            shapes[layer_name].insert(label)

        # Find existing connectivity in the layout.
        # Extract existing nets and shapes that belong to them.
        layout: db.Layout = top_cell.layout()
        l2n: db.LayoutToNetlist = lvs.extract_l2n(layout, top_cell)
        netlist_extracted: db.Netlist = l2n.netlist()
        top_circuit: db.Circuit = netlist_extracted.circuit_by_name(top_cell.name)

        nets_extracted = list(top_circuit.each_net())

        # Store shapes of each net as (layer_name, shape) tuples.
        shapes_by_net: Dict[db.Net, List[Tuple[str, db.Polygon]]] = dict()
        # net_by_shape: Dict[Tuple[str, db.Polygon], db.Net] = dict()
        for net in nets_extracted:
            shapes_of_net = list()
            lvs_layers = {l: l for l in shapes.keys()}
            lvs_layers[l_pdiffusion] = 'psd'
            lvs_layers[l_ndiffusion] = 'nsd'
            for layer_name, lvs_layer_name in lvs_layers.items():
                r = l2n.layer_by_name(lvs_layer_name)
                if r is not None:
                    # net_shapes = db.Shapes()  # Sink for shapes.
                    # l2n.shapes_of_net(net, r, True, net_shapes, 1)  # Get with properties.
                    # for s in net_shapes.each():
                    #     print("net shape", s)
                    net_shapes = l2n.shapes_of_net(net, r, True)
                    assert isinstance(net_shapes, db.Region)
                    # print(f"Shapes on layer {layer_name}, net {net}: {net_shapes}")
                    for s in net_shapes.each():
                        # print(layout.properties(s.prop_id))
                        assert isinstance(s, db.Polygon)
                        shapes_of_net.append((layer_name, s))
                        # net_by_shape[(layer_name, s)] = net
                else:
                    pass
                    # logger.debug(f"No such hierarchical layer '{layer_name}'.")

            shapes_by_net[net] = shapes_of_net

        # For each net find unconnected sets of terminal shapes.
        # Structure: {net name: {{shapes that are already connected}, ...}}
        pin_shapes_by_net: Dict[str, List[List[Tuple[str, db.Polygon]]]] = dict()
        for net, net_shapes in shapes_by_net.items():
            if net.name is not None:
                if net.name not in pin_shapes_by_net:
                    pin_shapes_by_net[net.name] = list()
                pin_shapes_by_net[net.name].append(net_shapes)

        for net, pins in pin_shapes_by_net.items():
            logger.debug(f"Number of pin shapes of net {net}: {len(pins)}")
            # if len(pins) == 1:
            #     logger.debug(f"Net is already routed: {net}")

        # # Construct two dimensional grid which defines the routing graph on a single layer.
        # grid = Grid2D((tech.grid_offset_x, tech.grid_offset_y),
        #               (cell_width, tech.grid_offset_y + tech.unit_cell_height),
        #               (tech.routing_grid_pitch_x, tech.routing_grid_pitch_y)
        #               )
        #
        # # Create base graph
        # graph = create_routing_graph_base(grid, tech)

        # Create base graph (v2)
        xs = list(range(tech.grid_offset_x, cell_width, tech.routing_grid_pitch_x))
        #ys = list(range(tech.grid_offset_y, tech.grid_offset_y + tech.unit_cell_height, tech.routing_grid_pitch_y))
        ys = tech.grid_ys
        #
        # # Embed off-grid lines for accessing transistor nodes.
        # for transistor, t_layout in transistor_layouts.items():
        #     terminals = t_layout.terminal_nodes()
        #     for net, ts in terminals.items():
        #         for t in ts:
        #             layer, (x, y) = t
        #             xs.append(x)
        #             ys.append(y)

        # Make cordinates unique and sort.
        xs = sorted(set(xs))
        ys = sorted(set(ys))

        graph = create_routing_graph_base_v2(xs, ys, tech)

        # Remove illegal routing nodes from graph and get a dict of legal routing nodes per layer.
        remove_illegal_routing_edges(graph, shapes, tech)

        # Remove pre-routed edges from graph.
        remove_existing_routing_edges(graph, shapes, tech)

        graph = add_via_nodes(graph, tech)

        # Create a list of terminal areas: [(net, [(layer, terminal_coord), ...]), ...]
        terminals_by_net = extract_terminal_nodes(graph, shapes, tech)

        # Extract terminals by using the netlist extraction functionality of KLayout.
        # This takes existing routing into account. Routing nodes that are already connected
        # by existing wires are put into a single terminal.
        terminals_by_net_lvs = extract_terminal_nodes_by_lvs(graph, pin_shapes_by_net, tech)

        # Find terminals that are already connected by routing and join them to single terminals.
        connected_terminals = {i: terms for i, (_net, terms) in enumerate(terminals_by_net_lvs)}
        # Create mapping from nodes to the terminal id where they are connected to.
        reverse_lut = {
            t: i for i, terms in connected_terminals.items() for t in terms
        }

        # Join terminals such that terminals that are connected by existing routes
        # are merged into a single terminal.
        joined_terminals = []
        processed = set()
        for net, terminals in terminals_by_net:
            connected_terminal_id = {reverse_lut[t] for t in terminals if t in reverse_lut}
            # print(net, connected_terminal_id)
            if len(connected_terminal_id) > 1:
                logger.error("Short circuit of nets detected.")
            if len(connected_terminal_id) > 0:
                i = list(connected_terminal_id)[0]
                if i not in processed:
                    processed.add(i)
                    joined_terminals.append((net, connected_terminals[i]))
            else:
                joined_terminals.append((net, terminals))

        # Update the list of terminals with the joined terminals.
        terminals_by_net = joined_terminals

        # Embed transistor terminal nodes in to routing graph.
        terminals_by_net.extend(embed_transistor_terminal_nodes(graph, transistor_layouts, tech))

        # Check if each net really has a routing terminal.
        # It can happen that there is none due to spacing issues.
        error = False
        # Check if each net has at least a terminal.
        net_names_of_terminals = {net for net, _ in terminals_by_net}
        for net_name in all_net_names:
            if net_name not in net_names_of_terminals:
                logger.error("Net '{}' has no routing terminal.".format(net_name))
                error = True

        if not self.debug_routing_graph:
            assert not error, "Nets without terminals. Check the routing graph (--debug-routing-graph)!"

        # Create virtual graph nodes for each net terminal.
        virtual_terminal_nodes = create_virtual_terminal_nodes(graph, terminals_by_net, io_pins, tech)

        if self.debug_routing_graph:
            # Display terminals on layout.
            routing_terminal_shapes = {
                l: top_cell.shapes(routing_terminal_debug_layers[l]) for l in tech.routing_layers.keys()
            }
            for net, ts in terminals_by_net:
                for layer, (x, y) in ts:
                    d = tech.routing_grid_pitch_x // 16
                    routing_terminal_shapes[layer].insert(pya.Box(pya.Point(x - d, y - d), pya.Point(x + d, y + d)))

        # Remove nodes that will not be used for routing.
        # Iteratively remove nodes of degree 1.
        while True:
            unused_nodes = set()
            for n in graph:
                if nx.degree(graph, n) <= 1:
                    if not _is_virtual_node_fn(n):
                        unused_nodes.add(n)
            if len(unused_nodes) == 0:
                break
            graph.remove_nodes_from(unused_nodes)

        if not nx.is_connected(graph):
            if self.debug_routing_graph:
                logger.warning('Routing graph is not connected.')
            else:
                assert False, 'Routing graph is not connected.'

        self._routing_graph = graph

        # TODO: SPLIT HERE
        # def _07_route(self):

        tech = self.tech
        spacing_graph = self._spacing_graph
        graph = self._routing_graph

        # Route
        if self.debug_routing_graph:
            # Write the full routing graph to GDS.
            logger.info("Skip routing and plot routing graph.")
            routing_trees = {'graph': self._routing_graph}
            return routing_trees
        else:
            logger.info("Start routing")
            # For each routing node find other nodes that are close enough such that they cannot be used
            # both for routing. This is used to avoid spacing violations during routing.
            logger.debug("Find conflicting nodes.")
            conflicts = dict()

            # Insert spacing rules from via nodes to metal.
            # This captures the spacing requirements caused by the via enclosure.
            spacing_graph = spacing_graph.copy()
            for (l1, l2, data) in via_layers.edges(data=True):
                via_layer = data['layer']
                via_width = tech.via_size[via_layer]
                for l in (l1, l2):
                    w_ext = via_width // 2 + tech.minimum_enclosure.get((l, via_layer), 0)
                    # Get min spacing on the metal layer.
                    # TODO: Check this!
                    if l in spacing_graph:
                        for l_next in list(spacing_graph[l]):
                            metal_spacing = spacing_graph[l][l_next]['min_spacing']
                            via_to_metal_spacing = metal_spacing + w_ext

                            # Update the spacing graph. Take the max if an entry already exists.
                            if l_next in spacing_graph and via_layer in spacing_graph[l_next]:
                                existing_via_to_metal_spacing = spacing_graph[l_next][via_layer]['min_spacing']
                                via_to_metal_spacing = max(via_to_metal_spacing, existing_via_to_metal_spacing)
                            spacing_graph.add_edge(via_layer, l_next, min_spacing=via_to_metal_spacing)

                    if l in spacing_graph and l in spacing_graph[l]:
                        metal_spacing = spacing_graph[l][l]['min_spacing']
                        via_to_metal_spacing = metal_spacing + w_ext

                        # Update the spacing graph. Take the max if an entry already exists.
                        if l in spacing_graph and via_layer in spacing_graph[l]:
                            existing_via_to_metal_spacing = spacing_graph[l][via_layer]['min_spacing']
                            via_to_metal_spacing = max(via_to_metal_spacing, existing_via_to_metal_spacing)
                        spacing_graph.add_edge(via_layer, l, min_spacing=via_to_metal_spacing)

                        # Create via-to-via spacing rule.
                        via_to_via_spacing = metal_spacing + w_ext * 2
                        if via_layer in spacing_graph and via_layer in spacing_graph[via_layer]:
                            existing_via_to_via_spacing = spacing_graph[via_layer][via_layer]['min_spacing']
                            via_to_via_spacing = max(via_to_via_spacing, existing_via_to_via_spacing)
                        spacing_graph.add_edge(via_layer, via_layer, min_spacing=via_to_via_spacing)

            # Prepare data structure for efficient region search of routing nodes.
            node_search = defaultdict(db.Shapes)
            for n in graph:
                if not _is_virtual_node_fn(n):
                    layer, (x, y) = n
                    p = db.Text(layer, x, y)
                    node_search[layer].insert(p)

            # For each node find nodes that would be in conflict when used at the same time.
            # Loop through all nodes in the routing graph graph.
            for n in graph:
                # Skip virtual nodes which have no physical representation.
                if not _is_virtual_node_fn(n):
                    layer, point = n
                    wire_width1 = tech.wire_width.get(layer, 0) // 2
                    node_conflicts = set()
                    if layer in spacing_graph:
                        # If there is a spacing rule defined involving `layer` then
                        # loop through all layers that have a spacing rule defined
                        # relative to the layer of the current node n.
                        for other_layer in spacing_graph[layer]:
                            if other_layer in tech.routing_layers:
                                # Find minimal spacing of nodes such that spacing rule is asserted.
                                wire_width2 = tech.wire_width.get(other_layer, 0) // 2
                                min_spacing = spacing_graph[layer][other_layer]['min_spacing']
                                margin = (wire_width1 + wire_width2 + min_spacing)

                                # Find nodes that are closer than the minimal spacing.
                                center = db.Point(*point)
                                v_margin = db.Vector(margin, margin)
                                search_box = db.Box(center - v_margin, center + v_margin)

                                # Find all nodes that are closer than 'margin'.
                                nodes_within_margin = node_search[other_layer].each_touching(search_box)

                                # Extract locations.
                                conflict_points = [shape.text_pos for shape in nodes_within_margin]

                                # Construct the lookup table for conflicting nodes.
                                for p in conflict_points:
                                    conflict_node = other_layer, (p.x, p.y)
                                    if conflict_node in graph:
                                        node_conflicts.add(conflict_node)
                    if node_conflicts:
                        conflicts[n] = node_conflicts

            # Find routing nodes that are reserved for a net. They cannot be used to route other nets.
            # (For instance the ends of a gate stripe.)
            reserved_nodes = defaultdict(set)
            for net, pins in terminals_by_net:
                for layer, p in pins:
                    n = layer, p
                    reserved = reserved_nodes[net]
                    reserved.add(n)
                    if n in conflicts:
                        for c in conflicts[n]:  # Also reserve nodes that would cause a spacing violation.
                            reserved.add(c)

            assert nx.is_connected(graph)

            if routing_nets is not None:
                # Route only selected nets.
                virtual_terminal_nodes = {net: virtual_terminal_nodes[net] for net in routing_nets}

            # Invoke router and store result.
            routing_trees = self.router.route(graph,
                                              signals=virtual_terminal_nodes,
                                              reserved_nodes=reserved_nodes,
                                              node_conflict=conflicts,
                                              is_virtual_node_fn=_is_virtual_node_fn
                                              )

            # TODO: Sanity check on result.
            return routing_trees

    def _08_draw_routes(self, shapes: Dict[str, db.Shapes], routing_trees: Dict[str, nx.Graph]):
        # Draw the layout of the routes.
        if routing_trees:
            for signal_name, rt in routing_trees.items():
                _draw_routing_tree(shapes,
                                   self._routing_graph,
                                   signal_name,
                                   rt, self.tech, self.debug_routing_graph)

            # Merge the polygons on all layers.
            # _merge_all_layers(shapes)


def _merge_all_layers(shapes: Dict[str, db.Shapes]):
    """
    Merge all polygons on all layers.
    """
    for layer_name, s in shapes.items():
        texts = [t.text for t in s.each() if t.is_text()]

        r = pya.Region(s)
        r.merge()
        s.clear()
        s.insert(r)

        # Copy text labels.
        for t in texts:
            s.insert(t)


def _is_virtual_node_fn(n) -> bool:
    """
    Check if the node is virtual and has no direct physical representation.
    :param n:
    :return:
    """
    return n[0].startswith('virtual')


def _is_virtual_edge_fn(e) -> bool:
    """
    Check if the edge connects to at least one virtual node.
    :param n:
    :return:
    """
    a, b = e
    return _is_virtual_node_fn(a) or _is_virtual_node_fn(b)
