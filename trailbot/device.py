import contextlib
import datetime
import enum
import logging
import pathlib
import threading
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

class _PhaseSet():
	def __init__(self) -> None:
		self.lock = threading.Lock()
		self.phases:typing.Dict[str, typing.Optional[str]] = {}

	def complete(self, phase_name:str, error:typing.Optional[str]) -> None:
		with self.lock:
			self.phases[phase_name] = error

	def wait(self, phase_name:str, timeout:int=30) -> None:
		start_time = time.time()
		while True:
			with self.lock:
				if phase_name in self.phases:
					error = self.phases[phase_name]
					if error is not None:
						raise RuntimeError(f"Phase {phase_name} failed with error {error}.")
					return
			if time.time() - start_time > timeout:
				raise RuntimeError(f"Phase {phase_name} timed out.")
			time.sleep(0.1)

class _GATTDeviceManagerBase(gatt.DeviceManager): # type: ignore
	def __init__(self, phase_set:_PhaseSet, mac_address:str, *args:typing.Any, **kwargs:typing.Any) -> None:
		super().__init__(*args, **kwargs)
		self.phase_set = phase_set
		self.mac_address = mac_address

	def device_discovered(self, device:gatt.Device) -> None:
		_LOGGER.info("Discovered device %s.", device.mac_address.upper())
		if device.mac_address.upper() == self.mac_address.upper():
			self.phase_set.complete("discover", None)

class _GATTDeviceBase(gatt.Device): # type: ignore
	def __init__(self, bluetooth_interface:typing.Optional[str], mac_address:str, *args:typing.Any, **kwargs:typing.Any) -> None:
		self.phase_set = _PhaseSet()
		manager = _GATTDeviceManagerBase(self.phase_set, mac_address, adapter_name=bluetooth_interface)
		super().__init__(manager=manager, mac_address=mac_address, *args, **kwargs)

	def connect_succeeded(self) -> None:
		super().connect_succeeded()
		_LOGGER.info("Connected to %s.", self.mac_address)
		self.phase_set.complete("connect", None)

	def connect_failed(self, error:str) -> None:
		super().connect_failed(error)
		self.phase_set.complete("connect", error)

	def disconnect_succeeded(self) -> None:
		super().disconnect_succeeded()
		_LOGGER.info("Disconnected from %s.", self.mac_address)
		self.phase_set.complete("disconnect", None)

	def services_resolved(self) -> None:
		super().services_resolved()
		_LOGGER.info("Services resolved on %s.", self.mac_address)
		self.phase_set.complete("resolve_services", None)

	def characteristic_write_value_succeeded(self, characteristic:gatt.Characteristic) -> None:
		_LOGGER.info("Write succeeded to %s on %s.", characteristic.uuid, self.mac_address)
		self.phase_set.complete("write_value", None)

	def characteristic_write_value_failed(self, _:gatt.Characteristic, error:str) -> None:
		self.phase_set.complete("write_value", error)

	def connect_and_write_value(self, value_to_write:bytes) -> None:
		thread = threading.Thread(target=self.manager.run)
		thread.start()
		try:
			self.manager.start_discovery()
			self.phase_set.wait("discover")
			self.manager.stop_discovery()
			self.connect()
			self.phase_set.wait("connect")
			self.phase_set.wait("resolve_services")
			service = next(s for s in self.services if s.uuid == _SERVICE_UUID)
			characteristic = next(c for c in service.characteristics if c.uuid == _CHARACTERISTIC_UUID)
			characteristic.write_value(value_to_write)
			self.phase_set.wait("write_value")
			self.disconnect()
			self.phase_set.wait("disconnect")
		finally:
			self.manager.stop()
			thread.join()

class Camera():
	def __init__(self, bluetooth_mac:str, wifi_ssid:str, bluetooth_interface:typing.Optional[str]=None, wifi_interface:typing.Optional[str]=None) -> None:
		self.bluetooth_mac = bluetooth_mac
		self.wifi_ssid = wifi_ssid
		self.bluetooth_interface = bluetooth_interface
		self.wifi_interface = wifi_interface or "wlan0"
	
	def enable_wifi(self) -> None:
		_LOGGER.info("Enabling Wi-Fi...")
		device = _GATTDeviceBase(mac_address=self.bluetooth_mac, bluetooth_interface=self.bluetooth_interface)
		device.connect_and_write_value(_ENABLE_WIFI_COMMAND)

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
		device = _GATTDeviceBase(mac_address=self.bluetooth_mac, bluetooth_interface=self.bluetooth_interface)
		device.connect_and_write_value(_DISABLE_WIFI_COMMAND)

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
