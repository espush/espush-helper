#!/usr/bin/env python
# encoding: utf-8

from __future__ import unicode_literals
from __future__ import print_function

from PyQt4.QtGui import QWidget, QApplication, QMessageBox, QMenu, QCursor, QDialog
from PyQt4.QtCore import Qt, QVariant, QUrl, QObject, QThread, pyqtSignal, QByteArray, QFile, QIODevice, QSize
from PyQt4 import QtGui, QtCore


import inputdlg


class InputDlg(QDialog):
    def __init__(self, parent=None, label1='', label2=''):
        QDialog.__init__(self, parent)
        self.ui = inputdlg.Ui_Dialog()
        self.ui.setupUi(self)
        if label1:
            self.ui.label1.setText(label1)
        if label2:
            self.ui.label2.setText(label2)

    def getValue(self):
        v1 = str(self.ui.line1.text().toLocal8Bit())
        v2 = str(self.ui.line2.text().toLocal8Bit())
        return v1, v2


def get_user_input(parent=None, label1='', label2=''):
    dlg = InputDlg(parent, label1, label2)
    rsp = dlg.exec_()
    if rsp == QDialog.Accepted:
        v1, v2 = dlg.getValue()
        return 1, v1, v2
    else:
        return 0, None, None

