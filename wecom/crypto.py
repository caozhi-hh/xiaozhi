"""
企业微信消息加解密 -- AES-256-CBC

实现企业微信回调 URL 的消息加解密算法：
- 密钥派生：Base64 解码 EncodingAESKey（43字符 + '='）
- 加密：random(16) + msg_len(4) + msg + corp_id → AES-256-CBC
- 签名：SHA1(sort(token, timestamp, nonce, encrypt))
"""
import base64
import hashlib
import socket
import struct
import time
import xml.etree.ElementTree as ET

from Crypto.Cipher import AES


class WeComCrypto:
    def __init__(self, token: str, encoding_aes_key: str, corp_id: str):
        self.token = token
        self.corp_id = corp_id
        # EncodingAESKey 是 43 个字符，Base64 解码后得到 32 字节 AES 密钥
        self.aes_key = base64.b64decode(encoding_aes_key + "=")
        self.iv = self.aes_key[:16]

    def verify_signature(self, signature: str, timestamp: str, nonce: str, encrypt: str) -> bool:
        """验证消息签名"""
        items = sorted([self.token, timestamp, nonce, encrypt])
        sha1 = hashlib.sha1("".join(items).encode()).hexdigest()
        return sha1 == signature

    def decrypt(self, encrypt_text: str) -> str:
        """解密消息，返回明文 XML 字符串"""
        cipher = AES.new(self.aes_key, AES.MODE_CBC, self.iv)
        plain = cipher.decrypt(base64.b64decode(encrypt_text))
        # 去除 PKCS#7 填充
        pad_len = plain[-1]
        plain = plain[:-pad_len]
        # 去掉前 16 字节随机字符串，4 字节消息长度
        msg_len = socket.ntohl(struct.unpack("I", plain[16:20])[0])
        msg = plain[20 : 20 + msg_len].decode("utf-8")
        corp_id = plain[20 + msg_len :].decode("utf-8")
        if corp_id != self.corp_id:
            raise ValueError(f"CorpID mismatch: expected {self.corp_id}, got {corp_id}")
        return msg

    def encrypt(self, reply_msg: str) -> str:
        """加密回复消息，返回 Base64 密文"""
        import os

        msg_bytes = reply_msg.encode("utf-8")
        corp_bytes = self.corp_id.encode("utf-8")
        # random(16) + msg_len(4 big-endian) + msg + corp_id
        raw = os.urandom(16) + struct.pack("I", socket.htonl(len(msg_bytes))) + msg_bytes + corp_bytes
        # PKCS#7 填充到 32 字节对齐
        pad_len = 32 - (len(raw) % 32)
        raw += bytes([pad_len] * pad_len)
        cipher = AES.new(self.aes_key, AES.MODE_CBC, self.iv)
        encrypted = cipher.encrypt(raw)
        return base64.b64encode(encrypted).decode("utf-8")

    def generate_signature(self, timestamp: str, nonce: str, encrypt: str) -> str:
        """生成签名"""
        items = sorted([self.token, timestamp, nonce, encrypt])
        return hashlib.sha1("".join(items).encode()).hexdigest()

    def wrap_encrypted_reply(self, reply_msg: str) -> str:
        """加密回复并包装成 XML 格式"""
        encrypt = self.encrypt(reply_msg)
        timestamp = str(int(time.time()))
        nonce = hashlib.md5(timestamp.encode()).hexdigest()[:10]
        signature = self.generate_signature(timestamp, nonce, encrypt)
        return (
            f"<xml>"
            f"<Encrypt><![CDATA[{encrypt}]]></Encrypt>"
            f"<MsgSignature><![CDATA[{signature}]]></MsgSignature>"
            f"<TimeStamp>{timestamp}</TimeStamp>"
            f"<Nonce><![CDATA[{nonce}]]></Nonce>"
            f"</xml>"
        )


def parse_encrypted_xml(xml_body: str) -> str:
    """从回调 XML 中提取 Encrypt 字段"""
    root = ET.fromstring(xml_body)
    encrypt = root.find("Encrypt")
    if encrypt is not None:
        return encrypt.text or ""
    raise ValueError("No <Encrypt> found in XML")


def parse_message_xml(xml_str: str) -> dict:
    """解析明文消息 XML，返回 dict"""
    root = ET.fromstring(xml_str)
    result = {}
    for child in root:
        result[child.tag] = child.text or ""
    return result
