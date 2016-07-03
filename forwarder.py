#!/usr/bin/env python
# -*- coding: utf-8 -*-

import argparse
import paho.mqtt.client as mqtt
from influxdb import InfluxDBClient
import re
import logging
import sys
import requests.exceptions


class MessageStore(object):
    def store_msg(self, node_name, measurement_name, value):
        raise NotImplementedError()

class InfluxStore(MessageStore):
    
    logger  = logging.getLogger("forwarder.InfluxStore")
    
    def __init__(self, host, port, username, password, database):
        self.influx_client = InfluxDBClient(host=host, port=port, username=username, password=password, database=database)
        #influx_client.create_database('sensors')

    def store_msg(self, node_name, measurement_name, value):
        influx_msg = {
                'measurement': measurement_name,
                'tags': {
                    'sensor_node': node_name,
                },
                'fields': {
                    'value': value,
                }
            }
        self.logger.debug("Writing InfluxDB point: %s", influx_msg)
        try:
            self.influx_client.write_points([influx_msg])
        except requests.exceptions.ConnectionError as e:
            self.logger.exception(e)

class MessageSource(object):

    def register_store(self, store):
        if not hasattr(self, '_stores'):
            self._stores = []
        self._stores.append(store)

    @property
    def stores(self):
        # return copy
        return list(self._stores)

class MQTTSource(MessageSource):

    logger  = logging.getLogger("forwarder.MQTTSource")

    def __init__(self, host, port, node_names):
        self.host = host
        self.port = port
        self.node_names = node_names
        self._setup_handlers()

    def _setup_handlers(self):
        self.client = mqtt.Client()

        def on_connect(client, userdata, flags, rc):
            self.logger.info("Connected with result code  %s", rc)
            # subscribe to /node_name/wildcard
            for node_name in self.node_names:
                topic = "/{node_name}/#".format(node_name=node_name)
                self.logger.info("Subscribing to topic %s for node_name %s", topic, node_name)
                client.subscribe(topic)

        def on_message(client, userdata, msg):
            self.logger.debug("Received MQTT message for topic %s with payload %s", msg.topic, msg.payload)
            regex = re.compile(ur'/(?P<node_name>\w+)/(?P<measurement_name>\w+)/?')
            match = regex.match(msg.topic)
            if match is None:
                self.logger.warn("Could not extract node name or measurement name from topic %s", msg.topic)
                return
            value = msg.payload
            try:
                value = float(value)
            except ValueError:
                pass
            node_name = match.group('node_name')
            if node_name not in self.node_names:
                self.logger.warn("Extract node_name %s from topic, but requested to receive messages for node_name %s", node_name, self.node_name)
            measurement_name = match.group('measurement_name')
            for store in self.stores:
                store.store_msg(node_name, measurement_name, value)

        self.client.on_connect = on_connect
        self.client.on_message = on_message

    def start(self):
        self.client.connect(self.host, self.port)
        # Blocking call that processes network traffic, dispatches callbacks and
        # handles reconnecting.
        # Other loop*() functions are available that give a threaded interface and a
        # manual interface.
        self.client.loop_forever()        

def main():
    parser = argparse.ArgumentParser(description='MQTT to InfluxDB bridge for IOT data.')
    parser.add_argument('--mqtt-host', required=True, help='MQTT host')
    parser.add_argument('--mqtt-port', required=True, help='MQTT port')
    parser.add_argument('--influx-host', required=True, help='InfluxDB host')
    parser.add_argument('--influx-port', required=True, help='InfluxDB port')
    parser.add_argument('--influx-user', required=True, help='InfluxDB username')
    parser.add_argument('--influx-pass', required=True, help='InfluxDB password')
    parser.add_argument('--influx-db', required=True, help='InfluxDB database')
    parser.add_argument('--node-name', required=True, help='Sensor node name', nargs='+')
    parser.add_argument('--verbose', help='Enable verbose output to stdout', default=False, action='store_true')
    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)
    else:
        logging.basicConfig(stream=sys.stdout, level=logging.INFO)

    store = InfluxStore(host=args.influx_host, port=args.influx_port, username=args.influx_user, password=args.influx_pass, database=args.influx_db)
    source = MQTTSource(host=args.mqtt_host, port=args.mqtt_port, node_names=args.node_name)
    source.register_store(store)
    source.start()

if __name__ == '__main__':
    main()