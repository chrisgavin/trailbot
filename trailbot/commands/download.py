import logging
import pathlib
import typing

import click

import trailbot.cli
import trailbot.device

_LOGGER = logging.getLogger(__name__)

@trailbot.cli.main.command(help="Download photos and videos from the camera.")
@click.option("--bluetooth-mac", type=str, required=True, help="The Bluetooth MAC address of the camera.")
@click.option("--wifi-ssid", type=str, required=True, help="The Wi-Fi SSID of the camera.")
@click.option("--bluetooth-interface", type=str, help="The Bluetooth interface to use.")
@click.option("--wifi-interface", type=str, help="The Wi-Fi interface to use.")
@click.option("--file-type", type=trailbot.device.FileType, multiple=True, help="Restrict the type of files to download.")
@click.option("--destination", type=pathlib.Path, required=True, help="Where to download the files to.")
def download(bluetooth_mac:str, wifi_ssid:str, bluetooth_interface:typing.Optional[str], wifi_interface:typing.Optional[str], file_type:typing.List[trailbot.device.FileType], destination:pathlib.Path) -> None:
	camera = trailbot.device.Camera(bluetooth_mac=bluetooth_mac, wifi_ssid=wifi_ssid, bluetooth_interface=bluetooth_interface, wifi_interface=wifi_interface)
	camera.enable_wifi()
	camera.connect_to_wifi()
	camera.fetch_files(file_types=file_type, destination=destination)
	camera.disable_wifi()
	_LOGGER.info("Done.")
