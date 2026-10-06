def desired_builder_count(
        current_round: int,
        initial_builders: int,
        maximum_builders: int,
        expansion_start_round: int,
        expansion_interval_rounds: int,
) -> int:
    """Return the builder budget without coupling it to future combat roles.

    The first wave gives one scout to each sector.  Later builders are added
    gradually, so they can reuse discovered roads and construct independent
    conveyor trunks without multiplying the expensive opening scan.
    """
    if current_round < expansion_start_round:
        return initial_builders
    additions = 1 + (
        current_round - expansion_start_round
    ) // expansion_interval_rounds
    return min(maximum_builders, initial_builders + additions)


def attack_force_budget(current_round, titanium, normal_interval):
    """Expand pressure only after the mining opening has earned its bank."""
    if current_round < 100 or titanium < 300:
        return 2, normal_interval, False
    if titanium < 600:
        return 3, 96, False
    if titanium < 1200:
        return 4, 64, True
    return 6, 32, True


def exploration_is_funded(controller):
    """Leave one worker and a short mine outlet in the shared treasury."""
    titanium, _ = controller.get_global_resources()
    reserve = (controller.get_builder_bot_cost()[0] + controller.get_harvester_cost()[0]
               + 4 * controller.get_conveyor_cost()[0])
    return titanium >= reserve + controller.get_road_cost()[0]


def fund_construction(controller, core_id):
    """Spend surplus refined Ax only when titanium blocks useful construction."""
    titanium, axionite = controller.get_global_resources()
    if not axionite:
        return
    reserve = (controller.get_builder_bot_cost()[0] + controller.get_harvester_cost()[0]
               + 8 * controller.get_conveyor_cost()[0])
    if titanium >= reserve:
        return
    retained = 0 if controller.get_hp(core_id) < 200 else 40
    amount = min(max(0, axionite - retained), (reserve - titanium + 3) // 4)
    if amount:
        controller.convert(amount)
