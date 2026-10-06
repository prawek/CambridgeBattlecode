"""Economic worker components.

Start at bot.BuilderBot: __init__ owns the state and run_turn orders actions.
The remaining classes supply methods and never initialize or duplicate state:
observation -> jobs -> network/routing -> construction, with scouting/movement
providing exploration and access to the current construction job.
"""
