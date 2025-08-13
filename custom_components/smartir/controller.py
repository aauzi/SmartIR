from abc import ABC, abstractmethod
import asyncio
from base64 import b64encode, b64decode
import binascii
import homeassistant.helpers.config_validation as cv
import requests
from typing import Any
import voluptuous as vol
import logging
import json

from homeassistant.const import ATTR_ENTITY_ID
from . import Helper

_LOGGER = logging.getLogger(__name__)

BROADLINK_CONTROLLER = 'Broadlink'
XIAOMI_CONTROLLER = 'Xiaomi'
MQTT_CONTROLLER = 'MQTT'
LOOKIN_CONTROLLER = 'LOOKin'
ESPHOME_CONTROLLER = 'ESPHome'
ZHA_TUYA_BROADLINK_CONTROLLER = 'ZHATuyaBroadlink'

ENC_BASE64 = 'Base64'
ENC_HEX = 'Hex'
ENC_PRONTO = 'Pronto'
ENC_RAW = 'Raw'

ZHA_TUYA_PREFIX = 'zha-tuya://'

BROADLINK_COMMANDS_ENCODING = [ENC_BASE64, ENC_HEX, ENC_PRONTO]
XIAOMI_COMMANDS_ENCODING = [ENC_PRONTO, ENC_RAW]
MQTT_COMMANDS_ENCODING = [ENC_RAW]
LOOKIN_COMMANDS_ENCODING = [ENC_PRONTO, ENC_RAW]
ESPHOME_COMMANDS_ENCODING = [ENC_RAW]
ZHA_TUYA_BROADLINK_COMMANDS_ENCODING = [ENC_BASE64, ENC_HEX, ENC_PRONTO, ENC_RAW]

def cv_controller_data(value: Any) -> Any:
    """Validate a controller_data."""

    try:
        return cv.string(value)
    except vol.Invalid:
        if not isinstance(value, dict):
            raise vol.Invalid("value should be a string or a dict")

    return dict(value)


def get_controller(hass, controller, encoding, controller_data, delay):
    """Return a controller compatible with the specification provided."""
    controllers = {
        BROADLINK_CONTROLLER: BroadlinkController,
        XIAOMI_CONTROLLER: XiaomiController,
        MQTT_CONTROLLER: MQTTController,
        LOOKIN_CONTROLLER: LookinController,
        ESPHOME_CONTROLLER: ESPHomeController,
        ZHA_TUYA_BROADLINK_CONTROLLER: ZHATuyaBroadlinkController
    }
    try:
        if controller in (BROADLINK_CONTROLLER, ZHA_TUYA_BROADLINK_CONTROLLER):
            if isinstance(controller_data, dict) and 'ieee' in controller_data:
                controller = ZHA_TUYA_BROADLINK_CONTROLLER
        return controllers[controller](hass, controller, encoding, controller_data, delay)
    except KeyError:
        raise Exception("The controller is not supported.")


class AbstractController(ABC):
    """Representation of a controller."""
    def __init__(self, hass, controller, encoding, controller_data, delay):
        self.check_encoding(encoding)
        self.hass = hass
        self._controller = controller
        self._encoding = encoding
        self._controller_data = controller_data
        self._delay = delay

    @abstractmethod
    def check_encoding(self, encoding):
        """Check if the encoding is supported by the controller."""
        pass

    @abstractmethod
    async def send(self, command):
        """Send a command."""
        pass


class BroadlinkController(AbstractController):
    """Controls a Broadlink device."""

    def check_encoding(self, encoding):
        """Check if the encoding is supported by the controller."""
        if encoding not in BROADLINK_COMMANDS_ENCODING:
            raise Exception("The encoding is not supported "
                            "by the Broadlink controller.")

    async def send(self, command):
        """Send a command."""
        commands = []

        if not isinstance(command, list):
            command = [command]

        for _command in command:
            if self._encoding == ENC_HEX:
                try:
                    _command = binascii.unhexlify(_command)
                    _command = b64encode(_command).decode('utf-8')
                except:
                    raise Exception("Error while converting "
                                    "Hex to Base64 encoding")

            if self._encoding == ENC_PRONTO:
                try:
                    _command = _command.replace(' ', '')
                    _command = bytearray.fromhex(_command)
                    _command = Helper.pronto2lirc(_command)
                    _command = Helper.lirc2broadlink(_command)
                    _command = b64encode(_command).decode('utf-8')
                except:
                    raise Exception("Error while converting "
                                    "Pronto to Base64 encoding")

            commands.append('b64:' + _command)

        service_data = {
            ATTR_ENTITY_ID: self._controller_data,
            'command':  commands,
            'delay_secs': self._delay
        }

        await self.hass.services.async_call(
            'remote', 'send_command', service_data)


class XiaomiController(AbstractController):
    """Controls a Xiaomi device."""

    def check_encoding(self, encoding):
        """Check if the encoding is supported by the controller."""
        if encoding not in XIAOMI_COMMANDS_ENCODING:
            raise Exception("The encoding is not supported "
                            "by the Xiaomi controller.")

    async def send(self, command):
        """Send a command."""
        service_data = {
            ATTR_ENTITY_ID: self._controller_data,
            'command':  self._encoding.lower() + ':' + command
        }

        await self.hass.services.async_call(
            'remote', 'send_command', service_data)


class MQTTController(AbstractController):
    """Controls a MQTT device."""

    def check_encoding(self, encoding):
        """Check if the encoding is supported by the controller."""
        if encoding not in MQTT_COMMANDS_ENCODING:
            raise Exception("The encoding is not supported "
                            "by the mqtt controller.")

    async def send(self, command):
        """Send a command."""
        service_data = {
            'topic': self._controller_data,
            'payload': command
        }

        await self.hass.services.async_call(
            'mqtt', 'publish', service_data)


class LookinController(AbstractController):
    """Controls a Lookin device."""

    def check_encoding(self, encoding):
        """Check if the encoding is supported by the controller."""
        if encoding not in LOOKIN_COMMANDS_ENCODING:
            raise Exception("The encoding is not supported "
                            "by the LOOKin controller.")

    async def send(self, command):
        """Send a command."""
        encoding = self._encoding.lower().replace('pronto', 'prontohex')
        url = f"http://{self._controller_data}/commands/ir/" \
                f"{encoding}/{command}"
        await self.hass.async_add_executor_job(requests.get, url)


class ESPHomeController(AbstractController):
    """Controls a ESPHome device."""

    def check_encoding(self, encoding):
        """Check if the encoding is supported by the controller."""
        if encoding not in ESPHOME_COMMANDS_ENCODING:
            raise Exception("The encoding is not supported "
                            "by the ESPHome controller.")

    async def send(self, command):
        """Send a command."""
        service_data = {'command':  json.loads(command)}

        await self.hass.services.async_call(
            'esphome', self._controller_data, service_data)


class ZHATuyaBroadlinkController(AbstractController):
    """Controls a Zigbee 3.0 Tuya device using ZHA."""

    def __init__(self, hass, controller, encoding, controller_data, delay):
        super().__init__(hass, controller, encoding, controller_data, delay)

        self._service_data = {
            'ieee': self._controller_data['ieee'],
            'endpoint_id': self._controller_data.get('endpoint_id', 1),
            'cluster_id': self._controller_data.get('cluster_id', 0xe004),
            'cluster_type': self._controller_data.get('cluster_type', 'in'),
            'command': self._controller_data.get('command', 2),
            'command_type': self._controller_data.get('command_type', 'server'),
            'params': {
                'code': None
            }
        }

    def check_encoding(self, encoding):
        """Check if the encoding is supported by the controller."""
        if encoding not in ZHA_TUYA_BROADLINK_COMMANDS_ENCODING:
            raise Exception("The encoding is not supported "
                            "by the ZHATuya Broadlink controller.")

    async def send(self, command):
        """Send a command."""
        if not isinstance(command, list):
            command = [command]

        service_data = dict(self._service_data)

        for _command in command:
            if self._encoding == ENC_BASE64:
                try:
                    _command = b64decode(_command)
                    _command = Helper.broadlink2tuya(_command)
                except Exception as e:
                    raise Exception("Error while converting "
                                    "Base64 to Tuya encoding")

            if self._encoding == ENC_HEX:
                try:
                    _command = binascii.unhexlify(_command)
                    _command = Helper.broadlink2tuya(_command)
                except:
                    raise Exception("Error while converting "
                                    "Hex to Tuya encoding")

            if self._encoding == ENC_PRONTO:
                try:
                    _command = _command.replace(' ', '')
                    _command = bytearray.fromhex(_command)
                    _command = Helper.pronto2lirc(_command)
                    _command = Helper.lirc2broadlink(_command)
                    _command = Helper.broadlink2tuya(_command)
                except:
                    raise Exception("Error while converting "
                                    "Pronto to Tuya encoding")

            service_data['params']['code'] = _command

            await self.hass.services.async_call(
                'zha', 'issue_zigbee_cluster_command', service_data)
            await asyncio.sleep(self._delay)
