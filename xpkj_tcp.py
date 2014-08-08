#!/usr/bin/env python
# -*- coding:utf-8 -*-
"""
    modbus网络的tcp数据采集插件
    1、device_id的组成方式为addr_slaveid
    2、设备类型为0，协议类型为modbus
    3、devices_info_dict需要持久化设备信息，启动时加载，变化时写入
"""
import sys
import json
import time
import socket
import paho.mqtt.client as mqtt
import threading
import traceback
import logging
import ConfigParser
import binascii
try:
    import paho.mqtt.publish as publish
except ImportError:
    # This part is only required to run the example from within the examples
    # directory when the module itself is not installed.
    #
    # If you have the module installed, just use "import paho.mqtt.publish"
    import os
    import inspect
    cmd_subfolder = os.path.realpath(os.path.abspath(os.path.join(os.path.split(inspect.getfile( inspect.currentframe() ))[0],"../src")))
    if cmd_subfolder not in sys.path:
        sys.path.insert(0, cmd_subfolder)
    import paho.mqtt.publish as publish

from json import loads, dumps

from libs.utils import *

# 设置系统为utf-8  勿删除
reload(sys)
sys.setdefaultencoding('utf-8')

# 全局变量
# 设备信息字典
devices_info_dict = dict()
thread_dict = dict()

# 切换工作目录
# 程序运行路径
procedure_path = cur_file_dir()
# 工作目录修改为python脚本所在地址，后续成为守护进程后会被修改为'/'
os.chdir(procedure_path)

# 日志对象
logger = logging.getLogger('xpkj_tcp')
hdlr = logging.FileHandler('./xpkj_tcp.log')
formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
hdlr.setFormatter(formatter)
logger.addHandler(hdlr)
logger.setLevel(logging.WARNING)

# 加载配置项
config = ConfigParser.ConfigParser()
config.read("./xpkj_tcp.cfg")
tcp_server_ip = config.get('server', 'ip')
tcp_server_port = int(config.get('server', 'port'))
mqtt_server_ip = config.get('mqtt', 'server')
mqtt_server_port = int(config.get('mqtt', 'port'))
gateway_topic = config.get('gateway', 'topic')
device_network = config.get('device', 'network')
data_protocol = config.get('device', 'protocol')

# 获取本机ip
ip_addr = get_ip_addr()

# 加载设备信息字典
devices_info_file = "devices.txt"


# 新增设备
def check_device(device_id, device_type, device_addr, device_port):
    # 如果设备不存在则设备字典新增设备并写文件
    if device_id not in devices_info_dict:
        # 新增设备到字典中
        devices_info_dict[device_id] = {
            "device_id": device_id,
            "device_type": device_type,
            "device_addr": device_addr,
            "device_port": device_port
        }
        logger.debug("发现新设备%r" % devices_info_dict[device_id])
        #写文件
        devices_file = open(devices_info_file, "w+")
        devices_file.write(dumps(devices_info_dict))
        devices_file.close()


def publish_device_data(device_id, device_type, device_addr, device_port, device_data):
    # device_data: 16进制字符串
    # 组包
    device_msg = {
        "device_id": device_id,
        "device_type": device_type,
        "device_addr": device_addr,
        "device_port": device_port,
        "data_protocol": data_protocol,
        "data": device_data
    }

    # MQTT发布
    publish.single(topic=gateway_topic,
                   payload=json.dumps(device_msg),
                   hostname=mqtt_server_ip,
                   port=mqtt_server_port)
    logger.info("向Topic(%s)发布消息：%s" % (gateway_topic, device_msg))


# 串口数据读取线程
# 串口数据读取线程
def process_mqtt():
    """
    :param data_sender: 业务数据队列
    :return:
    """
    # The callback for when the client receives a CONNACK response from the server.
    def on_connect(client, userdata, rc):
        logger.info("Connected with result code " + str(rc))
        # Subscribing in on_connect() means that if we lose the connection and
        # reconnect then subscriptions will be renewed.
        mqtt_client.subscribe("%s/#" % device_network)

    # The callback for when a PUBLISH message is received from the server.
    def on_message(client, userdata, msg):
        logger.info("收到数据消息" + msg.topic + " " + str(msg.payload))
        # 消息只包含device_cmd，16进制字符串
        cur_device_info = devices_info_dict[msg.topic]
        device_cmd = json.loads(msg.payload)["command"]
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            # Connect to server and send data
            sock.connect((tcp_server_ip, tcp_server_port))
            sock.sendall(device_cmd)
            received_data = sock.recv(1024)
            if "read_devlist" in device_cmd:
                global devices_info_dict
                devices_info_dict = json.loads(received_data)
                for device_info in devices_info_dict:
                    publish_device_data(device_info["device_id"],
                                        device_info["device_type"],
                                        device_info["device_addr"],
                                        device_info["device_port"],
                                        "")
            elif "run_dev" in device_cmd:
                # 是否需要再次读取控制状态？
                publish_device_data(cur_device_info["device_id"],
                                    cur_device_info["device_type"],
                                    cur_device_info["device_addr"],
                                    cur_device_info["device_port"],
                                    received_data)
        finally:
            sock.close()

    mqtt_client = mqtt.Client(client_id=device_network)
    mqtt_client.on_connect = on_connect
    mqtt_client.on_message = on_message

    mqtt_client.connect(mqtt_server_ip, mqtt_server_port, 60)

    # Blocking call that processes network traffic, dispatches callbacks and
    # handles reconnecting.
    # Other loop*() functions are available that give a threaded interface and a
    # manual interface.
    mqtt_client.loop_forever()


if __name__ == "__main__":

    addr = (tcp_server_ip, tcp_server_port)

    #Threadingxpkj_tcp从ThreadingMixIn和xpkj_tcp继承
    #class Threadingxpkj_tcp(ThreadingMixIn, xpkj_tcp): pass
    # 获取设备列表
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        # Connect to server and send data
        sock.connect((tcp_server_ip, tcp_server_port))
        sock.sendall("read_devlist\n")

        # 读取设备列表
        received_data = sock.recv(1024)
        global devices_info_dict
        devices_info_dict = json.loads(received_data)
        for device_info in devices_info_dict:
            check_device(device_info["device_id"],
                                device_info["device_type"],
                                device_info["device_addr"],
                                device_info["device_port"])
            publish_device_data(device_info["device_id"],
                                device_info["device_type"],
                                device_info["device_addr"],
                                device_info["device_port"],
                                "")
    finally:
        sock.close()

    # 启动线程监控MQTT
    mqtt_thread = threading.Thread(target=process_mqtt)
    mqtt_thread.start()

    while True:
        # 如果线程停止则创建
        if not mqtt_thread.isAlive():
            mqtt_thread = threading.Thread(target=process_mqtt)
            mqtt_thread.start()

        # res_result = modbus_client.read_input_registers(0, 1, unit=1)
        # print json.dumps(res_result.registers)

        logger.debug("处理完成，休眠5秒")
        time.sleep(5)
