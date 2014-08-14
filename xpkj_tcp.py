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
from libs.xpkj_define import *

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


def check_device(device_id, device_type, device_addr, device_port):
    """
    check device ,if device is not exist,then add device.
    :param device_id: network/device_name/eq_name
    :param device_type: device_type.eq_type
    :param device_addr: device_name
    :param device_port: eq_name
    :return:
    """
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



# 解析deviceslist消息
def parse_device_list(msg):
    lines = msg.split("\n")
    title_line = lines[0]
    titles = title_line.split("\t")
    device_id_index = -1
    device_type_index = -1
    device_state_index = -1
    device_name_index = -1
    device_addr_index = -1

    cur_devices_dict = dict()

    for key, value in enumerate(titles):
        if const.msg_devices_info_device_id == value:
            device_id_index = key
        elif const.msg_devices_info_device_type == value:
            device_type_index = key
        elif const.msg_devices_info_device_stat == value:
            device_state_index = key
        elif const.msg_devices_info_device_name == value:
            device_name_index = key
        elif const.msg_devices_info_network_id == value:
            device_addr_index = key

    if device_id_index == -1  \
            or device_type_index == -1 \
            or device_state_index == -1\
            or device_name_index == -1\
            or device_addr_index == -1:
        # 如果没有发现相应的字段，则返回空字典
        return cur_devices_dict

    for index in range(1, len(lines)):
        cur_line = lines[index]
        if len(cur_line.strip()) > 0:
            cur_values = cur_line.split('\t')
            device_info = {
                "device_id": cur_values[device_id_index],
                "device_type": cur_values[device_type_index],
                "device_state": cur_values[device_state_index],
                "device_name": cur_values[device_name_index],
                "device_addr": cur_values[device_addr_index]
            }
            cur_devices_dict[device_info["device_id"]] = device_info

    return cur_devices_dict


# 处理设备列表消息
def process_msg_device_list(msg):
    if len(msg) > 0:
        cur_devices_dict = parse_device_list(msg)
        devices_info_dict.clear()
        for origin_device_id in cur_devices_dict:
            # 每个ep（功能点）映射平台里的一个设备
            # 使用device_network/device_name/ep作为device_id
            # 使用ep作为device_addr
            cur_device_info = cur_devices_dict[origin_device_id]

            if cur_device_info["device_type"].upper() == const.device_type_8Relays:
                for index in range(0, 8):
                    # 8路继电器功能点固定为relay%d
                    device_addr = cur_device_info["device_name"]
                    device_port = "relay%d" % index + 1
                    device_type = "%s.%s" % (const.device_type_8Relays, "Relay")
                    device_id = "%s/%s/%s" % (device_network, device_addr, device_port)
                    check_device(device_id, device_type, device_addr, device_port)
                    publish_device_data(device_id, device_type, device_addr, device_port, "")
            elif cur_device_info["device_type"].upper() == const.device_type_UPI:
                device_addr = cur_device_info["device_name"]
                device_port = "Irep"
                device_type = "%s.%s" % (const.device_type_UPI, "Ired")
                device_id = "%s/%s/%s" % (device_network, device_addr, device_port)
                check_device(device_id, device_type, device_addr, device_port)
                publish_device_data(device_id, device_type, device_addr, device_port, "")
            elif cur_device_info["device_type"].upper() == const.device_type_8I8O:
                for index in range(0, 8):
                    # 8路IO功能点固定为din%d
                    device_addr = cur_device_info["device_name"]
                    device_port = "din%d" % index + 1
                    device_type = "%s.%s" % (const.device_type_8I8O, "Din")
                    device_id = "%s/%s/%s" % (device_network, device_addr, device_port)
                    check_device(device_id, device_type, device_addr, device_port)
                    publish_device_data(device_id, device_type, device_addr, device_port, "")


def process_msg_device_state(device_id, device_type, device_addr, device_port, msg):
    if len(msg) > 0:
        if "OK" in msg:
            values = msg.split("'")
            device_state = values[1]
            publish_device_data(device_id, device_type, device_addr, device_port, device_state)

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
        origin_device_cmd = json.loads(msg.payload)
        device_info = devices_info_dict[msg.topic]
        device_cmd = "%s\n%s|%s|%s\n" % (origin_device_cmd["command"],
                                          device_info["device_addr"],
                                          device_info["device_port"],
                                          origin_device_cmd["param"])
        # sock.sendall("read_dev\n8relays-266|relay1|state;\n")
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            # Connect to server and send data
            sock.connect((tcp_server_ip, tcp_server_port))
            received_data = sock.recv(1024)
            logger.debug("received_data:%r" % received_data)
            sock.sendall(device_cmd)
            received_data = sock.recv(1024)
            if "read_devlist" in device_cmd:
                # 字典清空
                process_msg_device_list(received_data)
            elif "run_dev" in device_cmd:
                # 是否需要再次读取控制状态？
                process_msg_device_state(device_info["device_id"],
                                         device_info["device_type"],
                                         device_info["device_addr"],
                                         device_info["device_port"],
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

    logger.debug("链接服务器%s:%d" % (tcp_server_ip, tcp_server_port))

    #Threadingxpkj_tcp从ThreadingMixIn和xpkj_tcp继承
    #class Threadingxpkj_tcp(ThreadingMixIn, xpkj_tcp): pass
    # 获取设备列表
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        # Connect to server and send data
        sock.connect((tcp_server_ip, tcp_server_port))
        # received_data = sock.recv(1024)
        # logger.debug("received_data：%r" % received_data)
        sock.sendall("read_devlist\n")
        received_data = sock.recv(1024)
        # print received_data
        process_msg_device_list(received_data)

        # 发送指令
        # sock.sendall("run_dev\n8relays-266|relay1|close();\n")
        # received_data = sock.recv(1024)
        # print received_data
        #
        # # 查询状态
        # sock.sendall("read_dev\n8relays-266|relay1|state;\n")
        # received_data = sock.recv(1024)
        # print received_data

    finally:
        sock.close()
"""
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
"""