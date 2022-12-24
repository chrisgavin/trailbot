import logging

import click

@click.group()
@click.option('--verbosity', default=logging.getLevelName(logging.INFO), type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]), help="Set the logging level.")
def main(verbosity:str) -> None:
	logging.basicConfig(level=verbosity)
