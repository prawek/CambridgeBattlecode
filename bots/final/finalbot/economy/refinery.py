"""Build a complete, short Ti + raw Ax -> refined Ax transaction.

Raw ore stays disabled in the general conveyor planner. These dedicated
inputs terminate at a foundry; only its refined output joins the core tree.
"""
from collections import deque

from cambc import EntityType, Environment, GameConstants
from finalbot.shared.constants import DIRECTIONS, ORTHOGONAL_DIRECTIONS
from finalbot.economy.refinery_routes import construction_tiles, input_route, road_clearance_cost

OUTPUT_OFFSETS = tuple((dx, dy) for dx in range(-3, 4) for dy in range(-3, 4)
                       if 0 < dx * dx + dy * dy <= 9)


def available(bot, pos, source=None, factory=False):
    cache = bot.tile_cache
    if pos is None or pos == source or cache.environment_at(pos) in (None, Environment.WALL):
        return False
    if factory and cache.environment_at(pos) != Environment.EMPTY:
        return False
    building = cache.building_at(pos)
    if building is None or building[0] == EntityType.ROAD:
        return True
    if factory and building == (EntityType.FOUNDRY, bot.team):
        return True
    # A spare port already sealed by a barrier can be reused. Productive
    # conveyors, including another worker's lanes, remain untouched.
    if source is None:
        return False
    if building == (EntityType.BARRIER, bot.team):
        return True
    if (building == (EntityType.CONVEYOR, bot.team)
            and pos.distance_squared(source) == 1
            and cache.entity_direction(cache.building_id_at(pos)) == pos.direction_to(source)):
        return True
    return (cache.environment_at(source) == Environment.ORE_TITANIUM
            and pos.distance_squared(source) == 1
            and building[1] == bot.team and building[0] in (EntityType.CONVEYOR, EntityType.BRIDGE)
            and getattr(bot, 'refinery_network_loads', {}).get(pos, 99) <= 1)


def plans(bot, current):
    """Choose a nearby connected output, then route two disjoint inputs."""
    cache = bot.tile_cache
    network = bot.known_connected_network()
    bot.refinery_network_loads = bot.known_network_loads(network)
    reachable = yield from construction_tiles(bot, current)
    sources = {Environment.ORE_AXIONITE: [], Environment.ORE_TITANIUM: []}
    for ore in cache.observed_tiles:
        env = cache.environment_at(ore)
        building = cache.building_at(ore)
        if env not in sources or not (building is None or building[0] in (EntityType.HARVESTER, EntityType.ROAD)):
            continue
        # Seeing and reaching a mine is insufficient when weapons occupy all
        # its ports. Do not let that nearest source hide a usable farther one.
        ports = [cache.neighbor(ore, d) for d in ORTHOGONAL_DIRECTIONS]
        if any(port in reachable and available(bot, port, ore)
               or cache.building_at(port) == (EntityType.FOUNDRY, bot.team)
               for port in ports if port is not None):
            sources[env].append(ore)
    ax_ores = sources[Environment.ORE_AXIONITE]
    titanium = sources[Environment.ORE_TITANIUM]
    if not ax_ores or not titanium:
        return None
    existing = {p for p, building in cache.buildings.items() if building == (EntityType.FOUNDRY, bot.team)}
    candidates = []
    for site in sorted(cache.observed_tiles, key=lambda p: (bot.core_distance(p), p.x, p.y)):
        yield
        if not available(bot, site, factory=True) or (existing and site not in existing):
            continue
        if not any(cache.neighbor(site, d) in reachable for d in DIRECTIONS):
            continue
        ax_choices = sorted(ax_ores, key=lambda p: (site.distance_squared(p), p.x, p.y))[:2]
        ti_choices = sorted(titanium, key=lambda p: (site.distance_squared(p), p.x, p.y))[:2]
        outputs = []
        for direction in ORTHOGONAL_DIRECTIONS:
            out = cache.neighbor(site, direction)
            if out not in reachable or not available(bot, out):
                continue
            receivers = [p for dx, dy in OUTPUT_OFFSETS if (p := cache.offset(out, dx, dy)) in network
                         and bot.network_receiver_accepts(p, out)
                         and (bot.is_core_receiver_tile(p) or bot.refinery_network_loads.get(p, 0) < 4)]
            if not receivers:
                continue
            receiver = min(receivers, key=lambda p: (bot.core_distance(p), p.x, p.y))
            outputs.append((out, receiver))
        for ax in ax_choices:
            for ti in ti_choices:
                if max(site.distance_squared(ax), site.distance_squared(ti)) > 225:
                    continue
                score = site.distance_squared(ax) + site.distance_squared(ti) + bot.core_distance(site) * 2
                candidates.extend((score, site, ax, ti, out, receiver)
                                  for out, receiver in outputs
                                  if out != ti and out.distance_squared(ax) > 1)
    # Round-robin distinct source pairs: four output directions around several
    # sites for one impossible pair must not consume the entire route budget.
    pairs = {}
    for candidate in sorted(candidates, key=lambda item: item[0]):
        pairs.setdefault((candidate[2], candidate[3]), []).append(candidate)
    pending = deque(iter(group) for group in pairs.values())
    attempts = []
    while pending and len(attempts) < 24:
        group = pending.popleft()
        candidate = next(group, None)
        if candidate is not None:
            attempts.append(candidate)
            pending.append(group)
    for _, site, ax, ti, out, receiver in attempts:
        reserved = {site, out, ax, ti}
        ax_ports = {cache.neighbor(ax, d) for d in ORTHOGONAL_DIRECTIONS}
        ti_path = yield from input_route(cache, ti, site,
                                        lambda p: p in reachable and available(bot, p, ti), reserved | ax_ports,
                                        team=bot.team)
        if ti_path is None:
            continue
        ti_tiles = {step[0] for step in ti_path}
        ti_ports = {cache.neighbor(ti, d) for d in ORTHOGONAL_DIRECTIONS}
        ax_path = yield from input_route(cache, ax, site,
                                        lambda p: p in reachable and available(bot, p, ax), reserved | ti_tiles | ti_ports,
                                        team=bot.team)
        if ax_path is None:
            continue
        steps = [(out, EntityType.BRIDGE, receiver, 'output'),
                 (site, EntityType.FOUNDRY, None, 'foundry')]
        steps.extend((*step, 'titanium') for step in ti_path)
        steps.extend((*step, 'axionite') for step in ax_path)
        steps.append((ti, EntityType.HARVESTER, None, 'titanium_source'))
        steps.append((ax, EntityType.HARVESTER, None, 'mine'))
        return steps
    return None


def step_matches(bot, step):
    pos, kind, extra, _ = step
    cache = bot.tile_cache
    if kind == EntityType.HARVESTER:
        source = cache.building_at(pos)
        return source is not None and source[0] == EntityType.HARVESTER
    if cache.building_at(pos) != (kind, bot.team):
        return False
    if kind == EntityType.BRIDGE:
        return bot.known_bridge_targets.get(pos) == extra
    if kind == EntityType.CONVEYOR:
        return cache.entity_direction(cache.building_id_at(pos)) == extra
    return True


def output_is_connected(bot, project):
    output = next((step for step in project if step[3] == 'output'), None)
    if output is None:
        return False
    source, _, receiver, _ = output
    return (receiver in bot.known_connected_network()
            and bot.network_receiver_accepts(receiver, source))


def recover_recipe(bot, now):
    """Reopen a completed transaction when an observed component is missing."""
    if now < getattr(bot, 'refinery_road_retry', 0):
        return
    recipe = getattr(bot, 'refinery_recipe', None)
    if recipe is None or now < getattr(bot, 'refinery_audit_round', 0):
        return
    bot.refinery_audit_round = now + 16
    visible = bot.tile_cache.visible_tiles
    if any(step[0] in visible and not step_matches(bot, step) for step in recipe):
        bot.refinery_project = recipe
        bot.refinery_index = 0
        bot.refinery_progress = now
        bot.refinery_road_project = None
        bot.refinery_road_attacks = {}


def construction_reserve(bot, controller, project):
    costs = {EntityType.BRIDGE: controller.get_bridge_cost,
             EntityType.FOUNDRY: controller.get_foundry_cost,
             EntityType.CONVEYOR: controller.get_conveyor_cost,
             EntityType.HARVESTER: controller.get_harvester_cost}
    missing = [step for step in project if not step_matches(bot, step)]
    prices = {kind: costs[kind]()[0] for kind in {step[1] for step in missing}}
    subtotal = sum(prices[step[1]] for step in missing)
    subtotal += sum(road_clearance_cost(bot.tile_cache, pos, bot.team)
                    for pos in {step[0] for step in missing})
    # Building the factory also raises the price of subsequent components.
    return subtotal + subtotal // 5 + controller.get_builder_bot_cost()[0]


def abandon_road_project(bot, now):
    """Pause both fresh planning and recipe recovery after blocked clearance."""
    bot.refinery_project = None
    bot.refinery_retry = now + 64
    bot.refinery_road_retry = now + 64
    bot.refinery_road_project = None
    bot.refinery_road_attacks = {}
    return False


def clear_enemy_road(bot, controller, current, pos, now):
    """Enter a hostile road before firing, retaining the saved recipe."""
    attempts = bot.refinery_road_attacks.get(pos, 0)
    if attempts >= 4:
        # A healed or rebuilt road must not absorb the worker for the match.
        return abandon_road_project(bot, now)
    if current != pos:
        path = bot.ore_walk(current, {pos})
        if path:
            bot.try_move_scout_step(controller, current, current.direction_to(path[0]))
        return True
    if controller.can_fire(pos):
        entity_id = bot.tile_cache.building_id_at(pos)
        hp = controller.get_hp(entity_id)
        controller.fire(pos)
        bot.refinery_road_attacks[pos] = attempts + 1
        bot.refinery_progress = now
        bot.last_progress_round = bot.rounds_alive
        if hp <= GameConstants.BUILDER_BOT_ATTACK_DAMAGE:
            bot.tile_cache.forget_building(pos)
            bot.network_memory.forget(pos)
            bot.connected_network_cache = None
    return True


def try_refinery(bot, controller, current):
    now = controller.get_current_round()
    if getattr(bot, 'refinery_project', None) is None:
        recover_recipe(bot, now)
    project = getattr(bot, 'refinery_project', None)
    if project is None:
        # Complete a preflighted mine connection before diverting the worker
        # to another construction site. Existing refinery repairs may preempt.
        if getattr(bot, 'refinery_recipe', None) is not None or bot.target_is_connection:
            return False
        if now < getattr(bot, 'refinery_retry', 100) or controller.get_global_resources()[0] < 150:
            return False
        search = getattr(bot, 'refinery_search', None)
        if search is None:
            search = bot.refinery_search = plans(bot, current)
        # Search resumes while normal mining and exploration continue.
        for _ in range(6):
            if controller.get_cpu_time_elapsed() >= 1100:
                break
            try:
                next(search)
            except StopIteration as result:
                bot.refinery_search = None
                bot.refinery_retry = now + 32
                if result.value is None:
                    return False
                if controller.get_global_resources()[0] < construction_reserve(bot, controller, result.value):
                    return False
                bot.refinery_project = project = result.value
                # The generator may have been suspended while another worker
                # changed the network. Never activate raw Ax into that route.
                if not output_is_connected(bot, project):
                    bot.refinery_project = None
                    return False
                bot.refinery_index = 0
                bot.refinery_progress = now
                break
        if project is None:
            return False
    if now - bot.refinery_progress > 80:
        next_step = project[bot.refinery_index] if bot.refinery_index < len(project) else None
        next_building = bot.tile_cache.building_at(next_step[0]) if next_step is not None else None
        road_pending = next_building is not None and next_building[0] == EntityType.ROAD and next_building[1] != bot.team
        road_attempted = (getattr(bot, 'refinery_road_project', None) is project
                          and bool(getattr(bot, 'refinery_road_attacks', {})))
        if road_pending or road_attempted:
            return abandon_road_project(bot, now)
        bot.refinery_project = None
        bot.refinery_retry = now + 64
        bot.refinery_road_project = None
        bot.refinery_road_attacks = {}
        return False
    if getattr(bot, 'refinery_road_project', None) is not project:
        bot.refinery_road_project = project
        bot.refinery_road_attacks = {}
    cache = bot.tile_cache
    while bot.refinery_index < len(project):
        pos, kind, extra, role = project[bot.refinery_index]
        building = cache.building_at(pos)
        if step_matches(bot, project[bot.refinery_index]):
            bot.refinery_index += 1
            continue
        if building is not None and building[0] == EntityType.ROAD and building[1] != bot.team:
            return clear_enemy_road(bot, controller, current, pos, now)
        if role == 'mine':
            # Earlier steps may have disappeared while the worker travelled
            # to the source. Restore them before enabling any raw output.
            missing = next((index for index, step in enumerate(project[:bot.refinery_index])
                            if not step_matches(bot, step)), None)
            if missing is not None:
                bot.refinery_index = missing
                return True
            if not output_is_connected(bot, project):
                bot.refinery_project = None
                bot.refinery_retry = now + 32
                return False
        source_role = 'titanium_source' if role == 'titanium' else 'mine'
        source = next((step[0] for step in project if step[3] == source_role), None)
        reclaim_seal = (role in ('titanium', 'axionite') and source is not None
                        and pos.distance_squared(source) == 1
                        and building == (EntityType.CONVEYOR, bot.team)
                        and cache.entity_direction(cache.building_id_at(pos)) == pos.direction_to(source))
        replace_input = (role == 'titanium' and source is not None and pos.distance_squared(source) == 1
                         and building is not None and building[1] == bot.team
                         and building[0] in (EntityType.BRIDGE, EntityType.CONVEYOR)
                         and bot.known_network_loads(bot.known_connected_network()).get(pos, 99) <= 1)
        if building is not None and not replace_input and not reclaim_seal and building not in ((EntityType.ROAD, bot.team), (EntityType.BARRIER, bot.team)):
            bot.refinery_project = None
            return False
        if current.distance_squared(pos) > 2 or (current == pos and kind != EntityType.CONVEYOR):
            approaches = {p for d in DIRECTIONS if (p := cache.neighbor(pos, d)) is not None
                          and bot.traversable_for_planning(None, p)}
            path = bot.ore_walk(current, approaches) if approaches else []
            if path:
                bot.try_move_scout_step(controller, current, current.direction_to(path[0]))
            return True
        if building is not None:
            if not controller.can_destroy(pos):
                return True
            controller.destroy(pos)
            cache.forget_building(pos)
            bot.network_memory.forget(pos)
        if not controller.can_build(kind, pos, extra):
            return True
        entity_id = controller.build(kind, pos, extra)
        cache.remember_building(pos, entity_id, kind, bot.team,
                                direction=extra if kind == EntityType.CONVEYOR else None)
        if kind == EntityType.BRIDGE:
            bot.known_bridge_targets[pos] = extra
            bot.known_bridge_ids[pos] = entity_id
        bot.refinery_progress = now
        bot.last_progress_round = bot.rounds_alive
        bot.connected_network_cache = None
        bot.refinery_index += 1
        return True
    bot.refinery_recipe = project
    bot.refinery_project = None
    bot.refinery_retry = now + 256
    bot.refinery_road_project = None
    bot.refinery_road_attacks = {}
    return False
