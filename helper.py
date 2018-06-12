#!/usr/bin/env python
# encoding: utf-8

from __future__ import unicode_literals
from __future__ import print_function

'''
主要功能：
1，登录系统，可退出登录，登陆后手机号密码不可输入
2，打开串口，可关闭，打开后 串口参数不可调整，关闭时忽略异常
3，串口监视有 3 个状态机，控制串口通讯时输入输出
4，固件烧录，可停止烧录，需要有进度条；
5，可发送 AT 指令，可载入/保存配置，CSV 格式；

配合教程的使用流程：
1，注册用户，这一步必须在平台完成
2，固件烧录，用到 helper，不需要用户登录
3，按需 AT 指令，用到 Helper
'''

'''
venv\Lib\site-packages\PyQt4\pyuic4.bat mainwnd.ui >mainwnd.py
venv\Lib\site-packages\PyQt4\pyuic4.bat inputdlg.ui >inputdlg.py
venv\Lib\site-packages\PyQt4\pyrcc4.exe res.qrc >res_rc.py
pyinstaller -F --noupx -w --win-no-prefer-redirects --clean --icon espush.ico helper.py
'''

import os
import sys
import json
import time
import hashlib
import binascii
import datetime
import functools
import threading

import serial
from serial.tools.list_ports import comports


from PyQt4 import QtNetwork
from PyQt4.QtGui import QWidget, QApplication, QMessageBox, QMenu, QCursor
from PyQt4.QtNetwork import QNetworkRequest, QNetworkReply
from PyQt4.QtCore import Qt, QVariant, QUrl, QObject, QThread, pyqtSignal, QByteArray, QFile, QIODevice, QSize
from PyQt4 import QtGui, QtCore


import serial_cmd
from flash_context import ESP8266Flasher
from serial_context import SerialContext
from utils import get_user_input


import mainwnd


ROMS_DIR = "down_roms"


class HelperWnd(QWidget):
    def __init__(self, parent=None):
        QWidget.__init__(self, parent)
        self.ui = mainwnd.Ui_Form()
        self.ui.setupUi(self)
        # 类变量区
        self._cmd_lists = []
        self._firmlists = []
        self._serial = None
        # 指示是否收到了一个 \n 新行,控制时间戳输出
        self._newline = True
        # 类变量，默认复选框
        self._timestamp = False
        self._hexformat = False
        self._add_crlf = True
        # 类变量
        # 初始化复选框
        self.init_default_chk()
        self.tableWidget_init()
        self.init_serial_args()
        self.load_cmdlists()
        # 固件列表
        self.load_firmlists()
        # 内容输出控件初始化
        self.init_text_out()
        # 串口按钮
        self.init_serial_btn()
        # 固件烧录按钮
        self.init_flasher_btn()
        # 右键菜单
        self.ctx_menu_init()

    def enable_table_changed_event(self):
        self.ui.tableWidget.cellChanged.connect(self.cell_content_changed)

    def disable_table_changed_event(self):
        try:
            self.ui.tableWidget.cellChanged.disconnect(self.cell_content_changed)
        except Exception, e:
            pass

    def init_flasher_btn(self):
        self.switch_flashbtn_closed()

    def ctx_menu_init(self):
        self.pop_menu = QMenu()
        self.pop_menu.addAction(self.ui.action_clear_log)
        self.pop_menu.addAction(self.ui.action_save_log)

    def init_default_chk(self):
        self.ui.timestamp_check.setCheckState(Qt.Checked if self._timestamp == True else Qt.Unchecked)
        self.ui.hex_check.setCheckState(Qt.Checked if self._hexformat == True else Qt.Unchecked)
        self.ui.crlf_check.setCheckState(Qt.Checked if self._add_crlf == True else Qt.Unchecked)

    def init_serial_thread(self):
        self._serial_c = SerialContext()
        self._serial_t = QThread()
        self._serial_c.moveToThread(self._serial_t)
        self._serial_c.open_serial_sig.connect(self._serial_c.open_serial)
        self._serial_c.write_data_sig.connect(self._serial_c.write_data)
        self._serial_c.close_serial_sig.connect(self._serial_c.close_serial)
        self._serial_c.data_received_sig.connect(self.serial_received)
        self._serial_c.serial_opened_sig.connect(self.serial_opened)
        self._serial_c.serial_closed_sig.connect(self.serial_closed)
        self._serial_t.start()

    def init_flasher_thread(self):
        self._flasher_c = ESP8266Flasher()
        self._flasher_t = QThread()
        self._flasher_c.moveToThread(self._flasher_t)
        self._flasher_t.start()
        self._flasher_c.begin_flash_sig.connect(self._flasher_c.begin_flash)
        self._flasher_c.abort_flash_sig.connect(self._flasher_c.abort_flash)
        self._flasher_c.conn_result_sig.connect(self.conn_result)
        self._flasher_c.flash_progress_sig.connect(self.flash_progress)
        self._flasher_c.flash_result_sig.connect(self.flash_result)
        self._flasher_c.console_sig.connect(self.console_log)

    def welcome(self):
        content = "<html>"
        content += u'<p>ESPush开发助手 v1.0</p>'
        content += u'<p>ESPush 是一个基于 ESP8266 WiFi 模组的便捷的物联网云开发平台，专为 ESP8266 优化。提供的固件可快速接入设备，提供 API 可随时对设备进行远程控制。</p>'
        url = u'https://espush.cn/api/portal/qqgroup'
        content += u'加入 <a href="%s">ESPush IoT QQ群</a> 进行讨论。</p><br/><br/>' % url
        content += "</html>"
        self.console_log(content)

    def warnbox(self, title, content):
        assert isinstance(title, unicode)
        assert isinstance(content, unicode)
        QtGui.QMessageBox.warning(self, title, content, u'确定')

    def warn_serial_not_open(self):
        content = u'请选择串口号并打开串口后，才可以继续此操作。'
        self.warnbox(u'警告', content)

    def init_text_out(self):
        self.ui.text_out.setOpenLinks(True)
        self.ui.text_out.setOpenExternalLinks(True)
        # 内容输出区域
        self.init_textout_sm()
        # 输出欢迎内容
        self.welcome()

    def init_serial_btn(self):
        # CLOSED OPENED
        self.switch_serialbtn_closed()

    def switch_serialbtn_closed(self):
        self._sbtn_state = 'CLOSED'
        self.ui.open_btn.setText(u'打开串口')

    def switch_serialbtn_opened(self):
        self._sbtn_state = 'OPENED'
        self.ui.open_btn.setText(u'关闭串口')

    # 烧录工具函数区
    # 借用串口状态，烧录也分为两个状态，即已打开，已关闭，简化状态机
    def switch_flashbtn_closed(self):
        self._fbtn_state = 'CLOSED'
        self.ui.flasher_btn.setText(u'开始烧录')
        # 已写入字节数
        self.written = 0
        # 时间消耗
        self.elapse = time.time()

    def switch_flashbtn_opened(self):
        self._fbtn_state = 'OPENED'
        self.ui.flasher_btn.setText(u'终止烧录')

    def checksum(self, content, csum):
        print(csum)
        print(len(content))
        print(type(content))
        md5 = lambda x: hashlib.md5(x).hexdigest()
        return md5(content) == csum

    def get_embed_firms(self, fileName):
        # ":/resources/blank.bin"
        baseName = ':/resources/'
        bFile = QFile(baseName + fileName)
        if not bFile.open(QIODevice.ReadOnly):
            self.console_log(u'读取内嵌资源 %s 出错！' % fileName)
            return
        content = bFile.readAll()
        return bytearray(content)

    def get_all_embed_firms(self):
        blank = self.get_embed_firms('blank.bin')
        if not blank:
            return
        boot = self.get_embed_firms('boot_v1.7.bin')
        if not boot:
            return
        esp_init_data = self.get_embed_firms('esp_init_data_default.bin')
        if not esp_init_data:
            return
        return {
            'blank': blank,
            'boot': boot,
            'init': esp_init_data,
        }

    def go_flash_continue(self, content):
        self.init_flasher_thread()
        firmwares = self.get_all_embed_firms()
        firmwares['app1'] = content
        device = self.ui.serial_combox.currentText()
        if device == "":
            return self.warnbox(u'错误', u'请选择有效的设备串口号')
        self.console_log(u'固件准备完毕，准备烧录到 %s' % device)
        self._flasher_c.begin_flash_sig.emit(device, firmwares)

    def local_firm_exist(self, firm):
        firmname = '%s/%d' % (ROMS_DIR, firm['id'])
        if not os.path.exists(firmname):
            return
        with open(firmname, 'rb') as fin:
            return fin.read()

    def get_firmware(self, firm):
        rsp = self.local_firm_exist(firm)
        if rsp:
            return rsp
        self.console_log(u'本地不存在，网上下载')
        rsp = self.down_firmfile(firm)
        if not rsp:
            self.console_log(u'下载失败')
            return
        return rsp

    def download_firmware(self, fid):
        assert isinstance(fid, (int, long))
        self.console_log(u'本地未找到有效的缓存固件')
        self.console_log(u'正从网络下载选定固件，请稍后')
        self.http = QtNetwork.QHttp(parent=self)
        self.http.done.connect(functools.partial(self.on_firmware_download_done, fid))
        print('fid: %d' % fid)
        self.url = QtCore.QUrl('https://espush.cn/api/portal/admin/down/firmwares/%d' % fid)
        self.http.setHost(self.url.host(), QtNetwork.QHttp.ConnectionModeHttps, self.url.port(443))
        self.download_firmware_reqid = self.http.get(self.url.path())

    def on_firmware_download_done(self, fid, error):
        if error:
            print(error)
            return self.warnbox(u'错误', u'固件下载出错')
        content = bytes(self.http.readAll())
        # hash 校验
        if not self.checksum(content, self._cur_firmware['checksum']):
            self.console_log(u'固件下载后数字校验错误!')
            return
        self.write_local_firm_file(fid, content)
        # 校验通过，且本地文件写入完毕后，继续烧录进程
        self.go_flash_continue(content)

    def write_local_firm_file(self, fid, content):
        # 文件夹是否存在，不存在则新增
        if not os.path.exists(ROMS_DIR):
            try:
                os.mkdir(ROMS_DIR)
            except IOError:
                self.console_log(u'创建下载 ROM 临时文件夹失败')
                return
        # 写入文件
        self.console_log(u'下载完毕，写入本地缓存文件')
        with open('%s/%d' % (ROMS_DIR, fid), 'wb') as fout:
            fout.write(content)

    def go_flash(self):
        '''
        1，首先获得目标固件
        2，如果本地有，则直接调用 go_flash_continue
        3，如果本地没有，则异步下载，下载完成后由回调函数调用 go_flash_continue 继续
        '''
        device = self.ui.serial_combox.currentText()
        if device == "":
            return self.warnbox(u'错误', u'请选择有效的设备串口号')
        pos = self.ui.roms_combox.currentIndex()
        if pos == -1:
            return self.warnbox(u'错误', u'请选择有效的固件')
        self._cur_firmware = self.ui.roms_combox.itemData(pos).toPyObject()[0]
        assert 'id' in self._cur_firmware
        assert 'checksum' in self._cur_firmware
        content = self.local_firm_exist(self._cur_firmware)
        if content and self.checksum(content, self._cur_firmware['checksum']):
            self.console_log(u'使用本地缓存固件')
            self.go_flash_continue(content)
        else:
            self.download_firmware(self._cur_firmware['id'])

    def go_abort(self):
        self.console_log(u'准备终止烧录过程')
        self._flasher_c.abort_flash_sig.emit()
    # 烧录工具函数

    def init_textout_sm(self):
        # CONSOLE, SERIAL
        self._textout_state = 'CONSOLE'

    def console_log(self, content):
        if self._textout_state == 'CONSOLE':
            self.ui.text_out.append(content)

    def serial_out(self, content):
        pass

    def load_firmlists(self):
        self.http = QtNetwork.QHttp(parent=self)
        self.http.done.connect(self.on_romlists_req_done)
        self.url = QtCore.QUrl("https://espush.cn/api/portal/admin/flasher/firmwares")
        self.http.setHost(self.url.host(), QtNetwork.QHttp.ConnectionModeHttps, self.url.port(443))
        self.get_romlist_reqid = self.http.get(self.url.path())

    def on_romlists_req_done(self, error):
        if error:
            print(error)
            return self.warnbox(u'错误', u'加载固件列表出错')
        rd = self.http.readAll()
        self._firmlists = json.loads(str(rd).decode('utf-8'))
        for item in self._firmlists:
            v = QVariant((item, ))
            self.ui.roms_combox.addItem(item['description'], userData=v)

    def init_serial_args(self):
        # 串口号
        ports = comports()
        self.ui.serial_combox.clear()
        ports = [el.device for el in ports]
        for port in ports:
            self.ui.serial_combox.addItem(port)
        # 波特率
        bauds = [4800, 9600, 38400, 74880, 115200, 576000]
        self.ui.baud_combox.clear()
        for baud in bauds:
            self.ui.baud_combox.addItem('%d' % baud)
        self.ui.baud_combox.setCurrentIndex(4)
        # 数据位
        for data in ['8', '7', '6', '5']:
            self.ui.databit_combox.addItem(data)
        # 校验位
        chks = ['None', 'Even', 'Mark', 'Odd', 'Space']
        self.ui.checkbit_combox.clear()
        for chk in chks:
            self.ui.checkbit_combox.addItem(chk)
        # 停止位
        stops = ['1', '1.5', '2']
        self.ui.stopbit_combox.clear()
        for stop in stops:
            self.ui.stopbit_combox.addItem(stop)
        # 流控
        self.ui.flowc_combox.clear()
        for item in  ['None']:
            self.ui.flowc_combox.addItem(item)

    def add_one_cmd(self, cmd):
        curRow = self.ui.tableWidget.rowCount()
        self.ui.tableWidget.setRowCount(self.ui.tableWidget.rowCount() + 1)
        # 加入复选框 from https://falsinsoft.blogspot.com/2013/11/qtablewidget-center-checkbox-inside-cell.html
        boxcontainer = QWidget()
        checkbox = QtGui.QCheckBox()
        checkbox.setCheckState(Qt.Checked if cmd.typ else Qt.Unchecked)
        checkbox.stateChanged.connect(functools.partial(self.cmd_hex_changed, curRow))
        layout1 = QtGui.QHBoxLayout(boxcontainer)
        layout1.addWidget(checkbox)
        layout1.setAlignment(Qt.AlignCenter)
        layout1.setContentsMargins(0, 0, 0, 0)
        boxcontainer.setLayout(layout1)
        self.ui.tableWidget.setCellWidget(curRow, 0, boxcontainer)
        # content
        content = QtGui.QTableWidgetItem()
        content.setText(cmd.content)
        self.ui.tableWidget.setItem(curRow, 1, content)
        # btn
        btncontainer = QWidget()
        btn = QtGui.QPushButton()
        assert isinstance(cmd.name, unicode)
        btn.setText(cmd.name[:5])
        btn.clicked.connect(functools.partial(self.send_cmd, curRow))
        layout1 = QtGui.QHBoxLayout(btncontainer)
        layout1.addWidget(btn)
        layout1.setAlignment(Qt.AlignCenter)
        layout1.setContentsMargins(0, 0, 0, 0)
        btncontainer.setLayout(layout1)
        self.ui.tableWidget.setCellWidget(curRow, 2, btncontainer)

    def clear_cmd_table(self):
        self.ui.tableWidget.clear()
        self.ui.tableWidget.setRowCount(0)

    def load_cmdlists(self):
        self._cmd_lists = [
            serial_cmd.SerialCmd(False, "AT", u"AT同步"),
            serial_cmd.SerialCmd(True, "41 54 0D 0A", u"AT同步"),
            serial_cmd.SerialCmd(False, "AT+GMR", u"版本号查询"),
            serial_cmd.SerialCmd(False, "AT+CIPSTATUS", u"网络状态"),
            serial_cmd.SerialCmd(False, "AT+SYSADC?", u"ADC读取"),
            serial_cmd.SerialCmd(False, "AT+WPS=1", u"开启WPS"),
            serial_cmd.SerialCmd(False, "AT+WPS=0", u"关闭WPS"),
            serial_cmd.SerialCmd(False, "AT+CWSTARTSMART=3", u"一键配网"),
            serial_cmd.SerialCmd(False, "AT+CWSTOPSMART", u"关闭配网"),
            serial_cmd.SerialCmd(False, "AT+RESTORE", u"系统重置"),
            serial_cmd.SerialCmd(False, "AT+GSLP=15000", u"深度睡眠"),
            serial_cmd.SerialCmd(False, "AT+RST", u"重启模组"),
        ]
        self.clear_cmd_table()
        for cmd in self._cmd_lists:
            self.add_one_cmd(cmd)

    def tableWidget_init(self):
        # 选中单元格虚线框
        self.ui.tableWidget.setFocusPolicy(Qt.NoFocus)
        # 列宽与属性
        self.ui.tableWidget.setColumnCount(3)
        self.ui.tableWidget.horizontalHeader().setClickable(False)
        self.ui.tableWidget.horizontalHeader().setMovable(False)
        self.ui.tableWidget.horizontalHeader().setResizeMode(QtGui.QHeaderView.Fixed)
        self.ui.tableWidget.verticalHeader().setResizeMode(QtGui.QHeaderView.Fixed)
        # 设置表头内容
        self.ui.tableWidget.setHorizontalHeaderLabels(['HEX', 'CMD', 'SEND'])
        # 设置表头加粗
        font = self.ui.tableWidget.font()
        font.setBold(True)
        self.ui.tableWidget.setFont(font)
        # 固定表头宽度
        self.ui.tableWidget.horizontalHeader().resizeSection(0, 32)
        self.ui.tableWidget.horizontalHeader().resizeSection(1, 150)
        self.ui.tableWidget.horizontalHeader().setStretchLastSection(True)

    def write_serial_cmd(self, cmd):
        if self._fbtn_state == 'OPENED':
            return self.warnbox(u'冲突', u'烧录固件时无法执行 AT 指令')
        assert isinstance(cmd, bytes)
        assert self._sbtn_state == 'OPENED'
        assert self._serial_c != None
        assert self._serial_c._serial != None
        out = cmd
        if self._add_crlf:
            out += b'\r\n'
        self._serial_c._serial.write(out)
        
    def write_raw_serial(self, data):
        assert isinstance(data, bytes)
        assert self._sbtn_state == 'OPENED'
        assert self._serial_c != None
        assert self._serial_c._serial != None
        self._serial_c._serial.write(data)

    def quick_cmd(self, cmd):
        if self._sbtn_state != 'OPENED':
            return self.warn_serial_not_open()
        if self._fbtn_state == 'OPENED':
            return self.warnbox(u'冲突', u'烧录固件时无法执行 AT 指令')
        self.write_raw_serial(cmd + b'\r\n')

    def closeEvent(self, evt):
        """
        :type evt: QCloseEvent
        :param evt:
        """
        evt.accept()

    def close_serial(self):
        self._serial_c.close_serial_sig.emit()

    # signal methods begin
    def flasher_btn_clicked(self):
        # 如果串口监控已经被打开了，先关闭之
        if self._sbtn_state == 'OPENED':
            return self.warnbox(u'关闭串口', u'烧录固件前请先关闭串口监控')

        if self._fbtn_state == 'OPENED':
            self.go_abort()
            self.switch_flashbtn_closed()
        elif self._fbtn_state == 'CLOSED':
            self.go_flash()
            self.switch_flashbtn_opened()
    
    def load_btn_clicked(self):
        filter = "config json (*.json)"
        path = QtGui.QFileDialog.getOpenFileName(self, u'读取配置', '', filter)
        if not path:
            return
        data = ''
        try:
            with open(path, 'rt') as fIn:
                data = fIn.read()
        except Exception, e:
            return self.warnbox(u'警告', u'文件读取失败')
        if not data:
            return self.warnbox(u'警告', u'配置内容加载错误')
        arr = []
        try:
            arr = json.loads(data)
        except Exception, e:
            return self.warnbox(u'警告', u'JSON 格式错误')
        if not arr:
            return self.warnbox(u'警告', u'配置为空，放弃加载')
        self.disable_table_changed_event()
        try:
            self.clear_cmd_table()
            self._cmd_lists = []
            for item in arr:
                if 'type' not in item:
                    continue
                if 'content' not in item:
                    continue
                cmd = serial_cmd.SerialCmd.fromJSON(item)
                self._cmd_lists.append(cmd)
                self.add_one_cmd(cmd)
        finally:
            self.enable_table_changed_event()
    
    def reset_btn_clicked(self):
        self.disable_table_changed_event()
        try:
            self.load_cmdlists()
        finally:
            self.enable_table_changed_event()
    
    def save_btn_clicked(self):
        filter = "config json (*.json)"
        path = QtGui.QFileDialog.getSaveFileName(self, u'保存配置', '', filter)
        if not path:
            return
        arr = []
        for cmd in self._cmd_lists:
            arr.append(cmd.serialize())
        body = json.dumps(arr, indent=4, ensure_ascii=False).encode('utf-8')
        with open(path, 'wt') as fout:
            fout.write(body)
        label = u'保存成功'
        QtGui.QMessageBox.information(self, u'提示', label, u'确定')

    def send_btn_clicked(self):
        if self._sbtn_state != 'OPENED':
            return self.warn_serial_not_open()
        cmdline = str(self.ui.cmd_input.text().toLocal8Bit())
        self.write_serial_cmd(cmdline)
    
    def serial_btn_clicked(self):
        if self._sbtn_state == 'OPENED':
            self.close_serial()
            return
        assert self._sbtn_state == 'CLOSED'
        # 是否正在烧录
        if self._fbtn_state == 'OPENED':
            return self.warnbox(u'错误', u'请先完成或终止烧录后再进行串口监听')
        # 要打开线程，先初始化线程信息
        self.init_serial_thread()
        port = str(self.ui.serial_combox.currentText().toLocal8Bit())
        baud = int(str(self.ui.baud_combox.currentText().toLocal8Bit()), 10)
        bytesize = int(str(self.ui.databit_combox.currentText().toLocal8Bit()), 10)
        parity = str(self.ui.checkbit_combox.currentText().toLocal8Bit())
        stopbits = str(self.ui.stopbit_combox.currentText().toLocal8Bit())
        args = {
            'port': port,
            'baud': baud,
            'bytesize': bytesize,
            'parity': parity,
            'stopbits': stopbits
        }
        self._serial_c.open_serial_sig.emit(args)

    def timestamp_check_changed(self, state):
        self._timestamp = state == 2

    def refresh_serial_btn_clicked(self):
        self.init_serial_args()

    def hex_check_changed(self, state):
        self._hexformat = state == 2
    
    def crlf_check_changed(self, state):
        self._add_crlf = state == 2

    def addline_btn_clicked(self):
        cmd = serial_cmd.SerialCmd(False, u"双击编辑内容", u"点击发送")
        self._cmd_lists.append(cmd)
        self.add_one_cmd(cmd)
        last = self.ui.tableWidget.item(len(self._cmd_lists) - 1, 1)
        self.ui.tableWidget.scrollToItem(last)

    def qbtn_sta_clicked(self):
        self.quick_cmd(b'AT+CWMODE=1')

    def qbtn_connect_router_clicked(self):
        label1 = u'请输入路由器 SSID 名称: '
        label2 = u'请输入路由器 SSID 密码: '
        flag, v1, v2 = get_user_input(self, label1, label2)
        if not flag:
            return
        if not v1:
            content = u'SSID名称为空，出错'
            QtGui.QMessageBox.warning(self, u'警告', content, u'确定')
            return
        # AT+CWJAP_DEF="HappyAirPort","12345678"
        cmd = b'AT+CWJAP_DEF="%s","%s"' % (v1, v2)
        self.quick_cmd(cmd)

    def qbtn_connect_espush_clicked(self):
        label1 = u'请输入 ESPush 云平台 应用ID: '
        label2 = u'请输入 ESPush 云平台 设备连接密钥: '
        flag, v1, v2 = get_user_input(self, label1, label2)
        if not flag:
            return
        if not v1:
            content = u'SSID名称为空，出错'
            QtGui.QMessageBox.warning(self, u'警告', content, u'确定')
            return
        # AT+CWJAP_DEF="HappyAirPort","12345678"
        cmd = b'AT+ESPUSH=%s,"%s","espush.cn",10001' % (v1, v2)
        self.quick_cmd(cmd)

    def qbtn_updata_clicked(self):
        title = u'数据上传'
        label = u'请输入待上传的 ASCII 字符串: '
        text, ok = QtGui.QInputDialog.getText(self, title, label)
        if not ok:
            return
        data = str(text.toLocal8Bit())
        if not data:
            return
        cmd = b'AT+EUPMSG=%s' % data
        self.quick_cmd(cmd)        

    def qbtn_scan_router_clicked(self):
        self.quick_cmd(b'AT+CWLAP')

    def qbtn_get_network_clicked(self):
        self.quick_cmd(b'AT+CIPSTA?')

    def qbtn_estatus_clicked(self):
        self.quick_cmd(b'AT+ESTATUS?')

    def qbtn_enter_stream_clicked(self):
        self.quick_cmd(b'AT+ESTREAM')

    def cell_content_changed(self, row, column):
        item = self.ui.tableWidget.item(row, column).text()
        if row >= len(self._cmd_lists):
            print('index out range, reset cmdlists?')
            return
        cmd = self._cmd_lists[row]
        cmd.content = str(item.toLocal8Bit())

    def show_ctx_menu(self):
        self.pop_menu.exec_(QCursor.pos())

    def clear_log(self):
        self.ui.text_out.clear()

    def save_log(self):
        caption = u'保存到...'
        filter = 'Text (*.txt)'
        path = QtGui.QFileDialog.getSaveFileName(self, caption, '', filter)
        if not path:
            return
        content = str(self.ui.text_out.document().toPlainText().toLocal8Bit())
        content = content.replace(b'\n', b'\r\n')
        with open(path, 'wb') as fout:
            fout.write(content)
        label = u'文件保存成功'
        QtGui.QMessageBox.information(self, u'提示', label, u'确定')
    # signal methods end

    # 串口读写的槽函数处理区
    def serial_opened(self):
        self.switch_serialbtn_opened()
    
    def serial_closed(self):
        self.switch_serialbtn_closed()
        self._serial_c = None
        self._serial_t = None
    
    def serial_received(self, data):
        # self.console_log(data)
        # running on main ui thread.
        # print('serial_received running on %d' % threading.currentThread().ident)
        text = b''
        # 如果需要输出时间戳
        if self._timestamp and self._newline:
            text += b'\n'
            text += datetime.datetime.now().strftime('%H:%M:%S')
            text += b' '
        # 如果为 HEX 显示模式
        if self._hexformat:
            text += b'%02X ' % data
        else:
            if data == 13:
                # ignore \r
                return
            try:
                text += chr(data)
            except Exception, e:
                print('exception...')
                print(type(data))
                print(repr(data))
                print('exception...')
        # 如果收到回车符，则下一行需要输出时间戳
        if data == 0x0A:
            self._newline = True
        else:
            self._newline = False
        self.ui.text_out.moveCursor(QtGui.QTextCursor.End)
        self.ui.text_out.insertPlainText(text)
        self.ui.text_out.moveCursor(QtGui.QTextCursor.End)
    # 串口读写的槽函数处理区

    # 烧录工具槽函数
    def conn_result(self, res):
        print('connect result is %r' % res)
        if res == 0:
            self.console_log(u'串口同步成功，烧录即将进行')
        if res == 1:
            self.console_log(u'同步串口失败，请检查所选串口并重试')
            self.switch_flashbtn_closed()

    def flash_progress(self, res, total):
        print('flash progress is %d, total %d, writed %d' % (res, total, self.written))
        self.written += res
        self.ui.progressBar.setValue( ( float(self.written) / total) * 100 )

    def flash_result(self, res, desc):
        print('flash result is %r' % res)
        elapse = time.time() - self.elapse
        if res == 1:
            self.console_log(u'烧录失败 %s 耗时 %d 秒' % (desc, elapse))
        if res == 0:
            self.console_log(u'固件烧录成功, 耗时 %d 秒\n\n' % elapse)
        self.switch_flashbtn_closed()
    # 烧录工具槽函数

    # 指令列表窗口槽函数区
    def send_cmd(self, rowid):
        if self._sbtn_state == 'CLOSED':
            return self.warn_serial_not_open()
        cmd = self._cmd_lists[rowid]
        cmdline = cmd.content.encode('utf-8')
        # 如果是 HEX 模式，则去空格，每俩字节翻译
        if cmd.typ == True:
            cmdline = binascii.a2b_hex(cmdline.replace(' ',''))
            # 16 进制模式下，不自动发送 \r\n
            self.write_raw_serial(cmdline)
        else:
            self.write_serial_cmd(cmdline)
    
    def cmd_hex_changed(self, rowid, state):
        cmd = self._cmd_lists[rowid]
        cmd.typ = state == 2
        print(self._cmd_lists)
    # 指令列表窗口槽函数区


def main():
    app = QApplication(sys.argv)
    wnd = HelperWnd()
    wnd.show()
    app.exec_()


if __name__ == '__main__':
    main()
