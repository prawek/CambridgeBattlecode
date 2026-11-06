"""Local entry point for both engines."""


class Player:
    def __init__(self):
        self.bot = None

    def run(self, controller):
        if self.bot is None:
            if hasattr(controller, "read_store"):
                from florent.main import Player as EnginePlayer
            else:
                from finalbot.player import Player as EnginePlayer
            self.bot = EnginePlayer()
        self.bot.run(controller)
