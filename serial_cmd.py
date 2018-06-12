#!/usr/bin/env python
# encoding: utf-8


from PyQt4.QtCore import Qt, QAbstractListModel, QVariant, QModelIndex
from PyQt4.QtGui import QWidget, QStyledItemDelegate, QLabel, QApplication, QStyle
from PyQt4 import QtGui, QtCore


try:
    _fromUtf8 = QtCore.QString.fromUtf8
except AttributeError:
    def _fromUtf8(s):
        return s


class SerialCmd(object):
    def __init__(self, typ, content, name=''):
        self.typ = typ
        self.content = content
        self.name = name

    def __str__(self):
        return 'CMD %s %s' % ('HEX' if self.typ == True else 'STR', self.content)

    def __repr__(self):
        return 'REPR %s %s' % ('HEX' if self.typ == True else 'STR', self.content)

    @staticmethod
    def fromJSON(obj):
        assert isinstance(obj, dict)
        assert 'type' in obj
        assert 'content' in obj
        typ = obj['type']
        content = obj['content']
        name = obj.get('name', u'点击发送')
        return SerialCmd(typ, content, name)

    def serialize(self):
        obj = {
            'type': self.typ,
            'content': self.content,
            'name': self.name
        }
        return obj