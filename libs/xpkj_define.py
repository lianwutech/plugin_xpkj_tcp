#!/usr/bin/env python
# -*- coding:utf-8 -*-

import const

# 设备消息定义
const.msg_devices_info_network_id       = 'num'        # 整形
const.msg_devices_info_device_name      = 'name'
const.msg_devices_info_device_id        = 'id'              # *:*:*
const.msg_devices_info_device_type      = 'type'            # string
const.msg_devices_info_device_ctype     = 'ctype'           #
const.msg_devices_info_device_stat      = 'stat'

# 设备类型
const.device_type_UPI                   = "UPI"
const.device_type_8I8O                  = "8I8O"
const.device_type_8Relays               = "8Relays".upper()

# 设备状态
const.device_state_offline              = 0
const.device_state_online               = 3

# 设备通讯类型
const.device_communicate_type_local     = 2
const.device_communicate_type_network   = 3

