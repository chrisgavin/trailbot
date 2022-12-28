import contextlib
import datetime
import enum
import logging
import pathlib
import time
import typing

import bs4
import gatt
import NetworkManager
import requests

_SERVICE_UUID = "0000ffe0-0000-1000-8000-00805f9b34fb"
_CHARACTERISTIC_UUID = "0000ffe9-0000-1000-8000-00805f9b34fb"
_DISABLE_WIFI_COMMAND = b"GPIO2"
_ENABLE_WIFI_COMMAND = b"GPIO3"
_WIFI_PASSWORD = "12345678"
_API_URL = "http://192.168.8.120"

_LOGGER = logging.getLogger(__name__)

class FileType(enum.Enum):
	PHOTO = "photo"
	VIDEO = "video"

_FILE_TYPE_URL_MAPPING = {
	FileType.PHOTO: "PHOTO",
	FileType.VIDEO: "MOVIE",
}

class _GATTDeviceBase(gatt.Device): # type: ignore
	def __init__(self, value_to_write:bytes, *args:typing.Any, **kwargs:typing.Any) -> None:
		super().__init__(*args, **kwargs)
		self.value_to_write = value_to_write

	def connect_succeeded(self) -> None:
		super().connect_succeeded()
		_LOGGER.info("Connected to %s.", self.mac_address)

	def connect_failed(self, error:str) -> None:
		super().connect_failed(error)
		_LOGGER.error("Connection to %s failed with error %s.", self.mac_address, error)

	def disconnect_succeeded(self) -> None:
		super().disconnect_succeeded()
		_LOGGER.info("Disconnected from %s.", self.mac_address)
		self.manager.stop()

	def services_resolved(self) -> None:
		super().services_resolved()
		_LOGGER.info("Services resolved on %s.", self.mac_address)

		service = next(s for s in self.services if s.uuid == _SERVICE_UUID)
		characteristic = next(c for c in service.characteristics if c.uuid == _CHARACTERISTIC_UUID)
		characteristic.write_value(self.value_to_write)

	def characteristic_write_value_succeeded(self, characteristic:gatt.Characteristic) -> None:
		_LOGGER.info("Write succeeded to %s on %s.", characteristic.uuid, self.mac_address)
		self.disconnect()

class Camera():
	def __init__(self, bluetooth_mac:str, wifi_ssid:str, bluetooth_interface:typing.Optional[str]=None, wifi_interface:typing.Optional[str]=None) -> None:
		self.bluetooth_mac = bluetooth_mac
		self.wifi_ssid = wifi_ssid
		self.bluetooth_interface = bluetooth_interface
		self.wifi_interface = wifi_interface or "wlan0"

		self.device_manager = gatt.DeviceManager(adapter_name=self.bluetooth_interface)
	
	def enable_wifi(self) -> None:
		_LOGGER.info("Enabling Wi-Fi...")
		device = _GATTDeviceBase(value_to_write=_ENABLE_WIFI_COMMAND, mac_address=self.bluetooth_mac, manager=self.device_manager)
		device.connect()
		self.device_manager.run()

	def connect_to_wifi(self) -> None:
		_LOGGER.info("Connecting to Wi-Fi...")
		wifi_interface = NetworkManager.NetworkManager.GetDeviceByIpIface(self.wifi_interface)
		NetworkManager.NetworkManager.AddAndActivateConnection(
			{
				"802-11-wireless": {
					"mode": "infrastructure",
					"ssid": self.wifi_ssid,
				},
				"802-11-wireless-security": {
					"key-mgmt": "wpa-psk",
					"psk": _WIFI_PASSWORD,
				},
				"connection": {
					"id": self.wifi_ssid,
					"type": "802-11-wireless",
				},
				"ipv4": {
					"method": "auto",
				},
				"ipv6": {
					"method": "auto",
				},
			},
			wifi_interface,
			"/",
		)
		while True:
			_LOGGER.info("Waiting for connection to complete...")
			wifi_interface = NetworkManager.NetworkManager.GetDeviceByIpIface(self.wifi_interface)
			if wifi_interface.State == NetworkManager.NM_DEVICE_STATE_ACTIVATED:
				if wifi_interface.ActiveConnection.Id == self.wifi_ssid:
					_LOGGER.info("Connected.")
					break
				else:
					raise Exception(f"Did not connect to Wi-Fi network. Instead reverted back to {wifi_interface.ActiveConnection.Id}.")
			else:
				time.sleep(1)

	def disconnect_from_wifi(self) -> None:
		for connection in NetworkManager.Settings.ListConnections():
			if connection.GetSettings()["connection"]["id"] == self.wifi_ssid:
				_LOGGER.info("Deleting connection to %s...", self.wifi_ssid)
				connection.Delete()

	def fetch_files(self, file_types:typing.Collection[FileType], destination:pathlib.Path, clean:bool) -> None:
		if not file_types:
			file_types = set(FileType)
		for file_type in file_types:
			url = f"{_API_URL}/DCIM/{_FILE_TYPE_URL_MAPPING[file_type]}"
			file_listing_response = requests.get(url)
			file_listing_response.raise_for_status()
			file_listing = bs4.BeautifulSoup(file_listing_response.text, "html5lib")
			file_table = file_listing.body.table
			for file_row in file_table.find_all("tr"):
				columns = file_row.find_all("td")
				if len(columns) <= 1:
					continue
				path = columns[0].a["href"]
				date = columns[2].text.strip().replace("/", "-")
				file_name = path.split("/")[-1]
				destination_name = f"{date} - {file_name}"
				full_destination = destination / destination_name
				if full_destination.exists():
					_LOGGER.info("Skipping %s because it already exists.", full_destination)
					continue
				temporary_full_destination = full_destination.with_suffix(full_destination.suffix + ".tmp")
				download_url = f"{_API_URL}{path}"
				_LOGGER.info("Downloading %s to %s...", download_url, full_destination)
				file_response = requests.get(download_url, stream=True)
				file_response.raise_for_status()
				size = int(file_response.headers["Content-Length"])
				try:
					with temporary_full_destination.open("wb") as file:
						for chunk in file_response.iter_content(chunk_size=1024):
							file.write(chunk)
							_LOGGER.info("Downloaded %s of %s.", file.tell(), size)
					actual_size = temporary_full_destination.stat().st_size
					if actual_size != size:
						raise Exception(f"Expected {temporary_full_destination} to be {size}, but it was only {actual_size}.")
					temporary_full_destination.rename(full_destination)
					_LOGGER.info("Downloaded %s.", full_destination)
					if clean:
						_LOGGER.info("Cleaning up %s...", download_url)
						delete_response = requests.get(download_url, params={"del": "1"})
						delete_response.raise_for_status()
						_LOGGER.info("Cleaned up %s.", download_url)
				finally:
					if temporary_full_destination.exists():
						temporary_full_destination.unlink()

	def set_date_time(self) -> None:
		date_time = datetime.datetime.now()
		date_string = date_time.strftime("%Y-%m-%d")
		time_string = date_time.strftime("%H:%M:%S")
		_LOGGER.info(f"Setting date and time to {date_string} {time_string}...")
		requests.get(f"{_API_URL}", params={"custom": "1", "cmd": "3005", "str": date_string}).raise_for_status()
		requests.get(f"{_API_URL}", params={"custom": "1", "cmd": "3006", "str": time_string}).raise_for_status()

	def disable_wifi(self) -> None:
		_LOGGER.info("Disabling Wi-Fi...")
		device = _GATTDeviceBase(value_to_write=_DISABLE_WIFI_COMMAND, mac_address=self.bluetooth_mac, manager=self.device_manager)
		device.connect()
		self.device_manager.run()

	@contextlib.contextmanager
	def enabled_wifi(self) -> typing.Generator[None, None, None]:
		try:
			self.enable_wifi()
			yield
		finally:
			self.disable_wifi()

	@contextlib.contextmanager
	def connected_to_wifi(self) -> typing.Generator[None, None, None]:
		try:
			self.connect_to_wifi()
			yield
		finally:
			self.disconnect_from_wifi()
