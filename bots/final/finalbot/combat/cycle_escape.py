"""Recover from confirmed movement cycles without discarding the assault."""

from collections import Counter, deque

from finalbot.shared.constants import DIRECTIONS


def escape_cycle(bot, controller, current):
    history = getattr(bot, 'movement_history', None)
    if history is None:
        history = bot.movement_history = deque(maxlen=16)
    history.append(current)
    now = controller.get_current_round()
    moving = sum(a != b for a, b in zip(history, list(history)[1:]))
    if len(history) == 16 and len(set(history)) <= 4 and moving >= 8:
        plan = getattr(bot, 'siege_plan', None)
        ore = plan[1] if plan is not None else getattr(bot, 'siege_probe_ore', None)
        if not hasattr(bot, 'deferred_siege_ores'):
            bot.deferred_siege_ores = {}
        if ore is not None:
            bot.deferred_siege_ores[ore] = now + 64
        if plan is not None:
            bot.siege_rejected[plan[0]] = now + 64
            bot.siege_plan = None
        bot._siege_search_key = None
        bot.cycle_escape_until = now + 6
    if now >= getattr(bot, 'cycle_escape_until', 0):
        return False
    visits = Counter(history)
    cache = bot.tile_cache
    choices = []
    for direction in DIRECTIONS:
        pos = cache.neighbor(current, direction)
        if pos is None:
            continue
        new_ground = sum(p not in cache.observed_tiles for d in DIRECTIONS
                         if (p := cache.neighbor(pos, d)) is not None)
        choices.append((visits[pos], -new_ground, direction))
    for _, _, direction in sorted(choices, key=lambda item: item[:2]):
        if bot.try_move_step(controller, direction):
            return True
    return False
