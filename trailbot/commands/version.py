import trailbot.cli
import trailbot.version

@trailbot.cli.main.command(help="Show the version of the application.")
def version() -> None:
	print(trailbot.version.version())
