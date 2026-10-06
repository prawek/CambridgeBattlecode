"""Infiltration and ammunition-supply components.

Start at bot.IntruderBot: __init__ owns the state and run orders actions.
Observation maintains core hypotheses; exploration/movement/launching find an
approach. Targeting selects the gunner, then supply_planning and
supply_construction establish and maintain its ammunition route.
"""
