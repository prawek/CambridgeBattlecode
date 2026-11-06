import unittest
from unittest.mock import Mock

from fcode import Direction, EntityType, Environment, Position, Team

from bots.final.florent.main import (
    Builder, Core, Economy, MapMemory, OWN_CORE, SPAWN_ORDER, SPAWN_ROLE, TransportNetwork,
    WORKER_STATUS, neighbors, pack, pack_status, unpack, unpack_status,
)


class FlorentSpawnTests(unittest.TestCase):
    def test_builder_reads_full_width_id_from_previous_turn(self):
        entity_id = (1 << 32) - 1
        core_position = Position(0, 0)
        core = Mock()
        core.get_position.return_value = core_position
        core.get_nearby_entities.return_value = []
        core.get_current_round.return_value = 0
        core.read_store.return_value = 0
        core.get_global_ammo.return_value = 0
        core.get_global_voltium.return_value = 0
        core.get_pit.return_value = None
        core.get_global_resources.return_value = 500
        core.get_builder_bot_cost.return_value = 30
        core.get_harvester_cost.return_value = 20
        core.get_conveyor_cost.return_value = 3
        core.get_nearby_tiles.return_value = [Position(2, 0)]
        core.get_tile_env.return_value = Environment.EMPTY
        core.can_spawn.return_value = True
        core.spawn_builder.return_value = entity_id
        core.write_store.side_effect = lambda _, value: value.to_bytes(4, "little")

        Core().run(core)
        store = dict(call.args for call in core.write_store.call_args_list)
        self.assertEqual(store[OWN_CORE], pack(core_position))
        self.assertEqual(store[SPAWN_ORDER], entity_id)
        self.assertEqual(store[SPAWN_ROLE], 1)

        controller = Mock()
        controller.get_id.return_value = entity_id
        controller.get_current_round.return_value = 0
        controller.read_store.return_value = 0
        worker = Builder()
        worker.local_action = Mock(return_value=True)
        worker.memory.observe = Mock()
        controller.get_nearby_entities.return_value = []
        worker.run(controller)
        controller.write_store.assert_not_called()

        controller.get_current_round.return_value = 1
        controller.read_store.side_effect = lambda slot: store.get(slot, 0)
        worker.run(controller)
        self.assertEqual(worker.role, 0)
        controller.write_store.assert_called_once_with(WORKER_STATUS, pack_status(1, None))

    def test_store_coordinates_round_trip_on_large_league_maps(self):
        tile = Position(37, 35)
        self.assertEqual(unpack(pack(tile)), tile)
        self.assertEqual(unpack_status(pack_status(999, tile)), (999, tile))


def economy_map(conveyors, harvesters, extra=()):
    memory = MapMemory()
    memory.transport = {
        tile: (EntityType.CONVEYOR, facing) for tile, facing in conveyors.items()
    }
    memory.harvesters = set(harvesters)
    memory.ores.update((tile, Environment.ORE_TITANIUM) for tile in harvesters)
    memory.terrain.update(memory.ores)
    memory.terrain.update((tile, Environment.EMPTY) for tile in (*conveyors, *extra))
    memory.adjacent.update((tile, neighbors(tile)) for tile in memory.terrain)
    memory.buildings.update((tile, (entity, EntityType.HARVESTER, Team.A))
                            for entity, tile in enumerate(harvesters, start=1))
    return memory


class FlorentEconomyTests(unittest.TestCase):
    def test_shared_trunk_caps_flow_and_a_second_intake_relaxes_it(self):
        trunk = Position(4, 4)
        left = Position(3, 4)
        conveyors = {
            trunk: Direction.EAST, left: Direction.EAST,
            Position(4, 3): Direction.SOUTH, Position(4, 5): Direction.NORTH,
        }
        ores = [Position(2, 4), Position(3, 3), Position(3, 5), Position(4, 2), Position(4, 6)]
        core = Position(5, 4)
        flow = TransportNetwork(economy_map(conveyors, ores), core)
        self.assertEqual(len(flow.served), 4)
        self.assertEqual(flow.loads[trunk], 4)
        self.assertNotIn(left, flow.residual)

        intake = Position(5, 6)
        conveyors[intake] = Direction.NORTH
        flow = TransportNetwork(economy_map(conveyors, ores), core)
        self.assertEqual(flow.served, set(ores))
        self.assertEqual(flow.loads[intake], 1)
        self.assertIn(intake, flow.residual)
        self.assertNotIn(intake, flow.open_inputs({intake}))

    def test_splitter_only_accepts_at_its_back_port(self):
        splitter = Position(4, 4)
        back = Position(3, 4)
        side = Position(4, 3)
        memory = economy_map({splitter: Direction.EAST}, (back, side))
        memory.transport[splitter] = EntityType.SPLITTER, Direction.EAST
        flow = TransportNetwork(memory, Position(5, 4))
        self.assertEqual(flow.served, {back})
        self.assertFalse(flow.accepts(splitter, side))

    def test_augmenting_path_moves_a_flexible_source_off_a_busy_trunk(self):
        trunk = Position(5, 4)
        intake = Position(4, 5)
        conveyors = {
            trunk: Direction.SOUTH, intake: Direction.EAST,
            Position(5, 3): Direction.SOUTH, Position(6, 4): Direction.WEST,
        }
        ores = (Position(4, 3), Position(4, 4), Position(5, 2), Position(6, 3), Position(7, 4))
        flow = TransportNetwork(economy_map(conveyors, ores), Position(5, 5))
        self.assertEqual(flow.served, set(ores))
        self.assertEqual(flow.loads[trunk], 4)
        self.assertEqual(flow.loads[intake], 1)

    def test_guard_seals_unused_port_without_touching_working_outlet(self):
        ore = Position(4, 4)
        port = Position(3, 4)
        worker = Position(3, 3)
        core = Position(5, 4)
        memory = economy_map({}, (ore,), (port, worker))
        memory.visible.update(memory.terrain)
        flow = TransportNetwork(memory, core)
        ct = Mock()
        ct.get_global_resources.return_value = 150
        ct.get_global_ammo.return_value = 0
        ct.get_builder_bot_cost.return_value = 30
        ct.get_harvester_cost.return_value = 20
        ct.get_conveyor_cost.return_value = 3
        ct.can_build_conveyor.return_value = True
        self.assertTrue(Economy().guard(ct, memory, flow, core, worker, Team.A, [], urgent=False))
        ct.build_conveyor.assert_called_once_with(port, Direction.EAST)
        ct.destroy.assert_not_called()

    def test_missing_belt_on_a_producing_lane_is_restored(self):
        ore, belt, worker, core = Position(3, 4), Position(4, 4), Position(4, 3), Position(5, 4)
        memory = economy_map({}, (ore,), (belt, worker))
        economy = Economy()
        economy.blueprint[belt] = Direction.EAST
        ct = Mock()
        ct.can_build_conveyor.return_value = True
        self.assertTrue(economy.repair(ct, memory, TransportNetwork(memory, core), worker))
        ct.build_conveyor.assert_called_once_with(belt, Direction.EAST)
