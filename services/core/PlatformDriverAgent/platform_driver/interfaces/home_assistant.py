# -*- coding: utf-8 -*- {{{
# vim: set fenc=utf-8 ft=python sw=4 ts=4 sts=4 et:
#
# Copyright 2020, Battelle Memorial Institute.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# This material was prepared as an account of work sponsored by an agency of
# the United States Government. Neither the United States Government nor the
# United States Department of Energy, nor Battelle, nor any of their
# employees, nor any jurisdiction or organization that has cooperated in the
# development of these materials, makes any warranty, express or
# implied, or assumes any legal liability or responsibility for the accuracy,
# completeness, or usefulness or any information, apparatus, product,
# software, or process disclosed, or represents that its use would not infringe
# privately owned rights. Reference herein to any specific commercial product,
# process, or service by trade name, trademark, manufacturer, or otherwise
# does not necessarily constitute or imply its endorsement, recommendation, or
# favoring by the United States Government or any agency thereof, or
# Battelle Memorial Institute. The views and opinions of authors expressed
# herein do not necessarily state or reflect those of the
# United States Government or any agency thereof.
#
# PACIFIC NORTHWEST NATIONAL LABORATORY operated by
# BATTELLE for the UNITED STATES DEPARTMENT OF ENERGY
# under Contract DE-AC05-76RL01830
# }}}


import random
from math import pi
import json
import sys
from platform_driver.interfaces import BaseInterface, BaseRegister, BasicRevert
from volttron.platform.agent import utils #added this to pull from config store 
from volttron.platform.vip.agent import Agent
import logging
import requests
from requests import get

_log = logging.getLogger(__name__)
type_mapping = {"string": str,
                "int": int,
                "integer": int,
                "float": float,
                "bool": bool,
                "boolean": bool}

class HomeAssistantRegister(BaseRegister):
    def __init__(self, read_only, pointName, units, reg_type, attributes, entity_id,
                 default_value=None, description=''):
        super(HomeAssistantRegister, self).__init__("byte", read_only, pointName, units,
                                           description='')
        self.reg_type = reg_type
        self.attributes = attributes
        self.entity_id = entity_id
        self.value = None

class Interface(BasicRevert, BaseInterface):
    def __init__(self, **kwargs):
        super(Interface, self).__init__(**kwargs)
        self.point_name = None
  
    def configure(self, config_dict, registry_config_str): # grabbing from config
        self.ip_address = config_dict.get("ip_address", None)
        self.access_token = config_dict.get("access_token", None)
        self.port = config_dict.get("port", None)

        # Check for None values
        if self.ip_address is None:
            _log.error("IP address is not set.")
            raise ValueError("IP address is required.")
        if self.access_token is None:
            _log.error("Access token is not set.")
            raise ValueError("Access token is required.")
        if self.port is None:
            _log.error("Port is not set.")
            raise ValueError("Port is required.")
        
        self.parse_config(registry_config_str) 
        
    def get_point(self, point_name):
        register = self.get_register_by_name(point_name)
        return register.value

    def _set_point(self, point_name, value):
        register = self.get_register_by_name(point_name)
        if register.read_only:
            raise RuntimeError(
                "Trying to write to a point configured read only: " + point_name)
        register.value = register.reg_type(value) # setting the value

        # Changing lights values in home assistant based off of register value. 
        if "light." in register.entity_id:
            if point_name == "state":
                if register.value == True:
                    self.turn_on_lights(register.entity_id)

                elif register.value == False:
                    self.turn_off_lights(register.entity_id)

            elif point_name == "brightness":
                self.change_brightness(register.entity_id, register.value)

        # Changing thermostat values. 
        elif "climate." in register.entity_id:
            if point_name == "state":
                if register.value == 1:
                    self.change_thermostat_mode(entity_id=register.entity_id, mode="off")
                elif register.value == 2:
                    self.change_thermostat_mode(entity_id=register.entity_id, mode="heat")
                elif register.value == 3:
                    self.change_thermostat_mode(entity_id=register.entity_id, mode="cool")
                elif register.value == 4:
                    self.change_thermostat_mode(entity_id=register.entity_id, mode="auto")
                else:
                    _log.error(f"{register.value} is not a supported thermostat mode. (1: Off, 2: heat, 3: Cool, 4: Auto)")
            elif point_name == "temperature":
                self.set_thermostat_temperature(entity_id=register.entity_id, temperature=register.value)
        else:
            pass
        return register.value
    
    def get_entity_data(self, point_name):
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }
        url = f"http://{self.ip_address}:{self.port}/api/states/{point_name}" # the /states grabs current state AND attributes of a specific entity
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.json() # return the json attributes from entity
        else:
            _log.error(f"Request failed with status code {response.status_code}: {point_name} {response.text}")
            return None
        
    def _scrape_all(self):
        result = {}
        read_registers = self.get_registers_by_type("byte", True)
        write_registers = self.get_registers_by_type("byte", False)

        for register in read_registers + write_registers:
            entity_id = register.entity_id 
            entity_data = self.get_entity_data(entity_id) # Using Entity ID to get data
            if "climate." in entity_id: # handling thermostats. 
                if register.point_name == "state":
                    state = entity_data.get("state", None)

                    # Giving thermostat states an equivilent number. 
                    if state == "off":
                        register.value = 1
                        result[register.point_name] = 1
                    elif state == "heat":
                        register.value = 2
                        result[register.point_name] = 2
                    elif state == "cool":
                        register.value = 3
                        result[register.point_name] = 3
                # Assigning attributes
                else:
                    attribute = entity_data.get("attributes", {}).get(f"{register.point_name}", 0)
                    register.value = attribute
                    result[register.point_name] = attribute
            else: # handling everything else
                if register.point_name == "state":
                    
                    state = entity_data.get("state", None)
                    register.value = state
                    result[register.point_name] = state
                # Assigning attributes
                else:
                    attribute = entity_data.get("attributes", {}).get(f"{register.point_name}", 0)
                    register.value = attribute
                    result[register.point_name] = attribute

        return result

    def parse_config(self, configDict):

        if configDict is None:
            return
        for regDef in configDict:

            if not regDef['Entity ID']:
                continue

            read_only = str(regDef.get('Writable', '')).lower() != 'true'
            entity_id = regDef['Entity ID']
            self.point_name = regDef['Volttron Point Name']
            self.units = regDef['Units']
            description = regDef.get('Notes', '')
            
            default_value = str(regDef.get("Starting Value", 'sin')).strip()
            if not default_value:
                default_value = None
            type_name = regDef.get("Type", 'string')
            reg_type = type_mapping.get(type_name, str)
            attributes = regDef.get('Attributes', {})
            register_type = HomeAssistantRegister

            register = register_type(
                read_only,
                self.point_name,
                self.units,
                reg_type,
                attributes,
                entity_id,
                default_value=default_value,
                description=description)

            if default_value is not None:
                self.set_default(self.point_name, register.value)

            self.insert_register(register)

    def turn_off_lights(self, entity_id):
        url = f"http://{self.ip_address}:{self.port}/api/services/light/turn_off"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

        try:
            payload = {
                "entity_id": entity_id,
            }
            response = requests.post(url, headers=headers, data=json.dumps(payload))
            if response.status_code == 200:
                _log.info(f"Turned off {entity_id}")
        except:
            pass

    def turn_on_lights(self, entity_id):
        url2 = f"http://{self.ip_address}:{self.port}/api/services/light/turn_on"
        headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json",
        }
        try:
            payload = {
                "entity_id": f"{entity_id}"
            }
            response = requests.post(url2, headers=headers, data=json.dumps(payload))
            if response.status_code == 200:
                    _log.info(f"Turned on {entity_id}")
        except:
            pass

    def change_thermostat_mode(self, entity_id, mode):
        # Check if enttiy_id startswith climate.
        if not entity_id.startswith("climate."):
            _log.error(f"{entity_id} is not a valid thermostat entity ID.")
            return
        # Build header
        url = f"http://{self.ip_address}:{self.port}/api/services/climate/set_hvac_mode"
        headers = {
                "Authorization": f"Bearer {self.access_token}",
                "content-type": "application/json",
        }
        # Build data
        data = {
            "entity_id": entity_id,
            "hvac_mode": mode,
        }
        # Post data
        response = requests.post(url, headers=headers, json=data)
        if response.status_code == 200:
            _log.info(f"Successfully changed the mode of {entity_id} to {mode}")
        else:
            _log.info(f"Failed to change the mode of {entity_id}. Response: {response.text}")

    def set_thermostat_temperature(self, entity_id, temperature):
        # Check if the provided entity_id starts with "climate."
        if not entity_id.startswith("climate."):
            _log.error(f"{entity_id} is not a valid thermostat entity ID.")
            return

        url = f"http://{self.ip_address}:{self.port}/api/services/climate/set_temperature"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "content-type": "application/json",
        }
        
        if self.units == "C":
            converted_temp = round((temperature - 32) * 5/9, 1)
            _log.info(f"Converted temperature {converted_temp}")
            data = {
                "entity_id": entity_id,
                "temperature": converted_temp,
            }
        else:
            data = {
                "entity_id": entity_id,
                "temperature": temperature,
            }
        
        response = requests.post(url, headers=headers, json=data)
        
        if response.status_code == 200:
            _log.info(f"Successfully changed the temperature of {entity_id} to {temperature}")
        else:
            _log.error(f"Failed to change the temperature of {entity_id}. Response: {response.text}")

    def change_brightness(self, entity_id, value):
        url2 = f"http://{self.ip_address}:{self.port}/api/services/light/turn_on"
        headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json",
        }
        try:
            # ranges from 0 - 255 for most lights
            payload = {
                "entity_id": f"{entity_id}",
                "brightness": value,
            }
            response = requests.post(url2, headers=headers, data=json.dumps(payload))
            if response.status_code == 200:
                    _log.info(f"Turned on {entity_id}")
        except:
            pass
