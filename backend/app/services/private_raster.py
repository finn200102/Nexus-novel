"""Bounded PNG verification without filesystem codecs or provider URL fetching."""
import base64
import struct
import zlib

MAX_IMAGE_BYTES = 8 * 1024 * 1024


def decode_png(value, expected_size):
    if not isinstance(value, str) or not 0 < len(value) <= (MAX_IMAGE_BYTES * 4 // 3 + 8):
        raise ValueError('Portrait must be bounded base64 raster data')
    try:
        body = base64.b64decode(value, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError('Portrait base64 is invalid') from exc
    if len(body) > MAX_IMAGE_BYTES or body[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError('Portrait must be a bounded PNG')
    position, chunks, compressed, dimensions, ended = 8, 0, bytearray(), None, False
    while position < len(body):
        if position + 12 > len(body): raise ValueError('Invalid PNG structure')
        length = int.from_bytes(body[position:position+4], 'big')
        kind = body[position+4:position+8]; end = position + length + 12
        if end > len(body) or length > MAX_IMAGE_BYTES: raise ValueError('Invalid PNG chunk')
        data = body[position+8:end-4]
        if zlib.crc32(kind + data) & 0xffffffff != int.from_bytes(body[end-4:end], 'big'):
            raise ValueError('Invalid PNG checksum')
        chunks += 1
        if chunks > 4096: raise ValueError('Too many PNG chunks')
        if kind == b'IHDR':
            if dimensions is not None or position != 8 or length != 13: raise ValueError('Invalid PNG header')
            width, height, depth, colour, compression, filtering, interlace = struct.unpack('>IIBBBBB', data)
            if f'{width}x{height}' != expected_size or width * height > 2_000_000 or depth != 8 or colour not in {0, 2, 4, 6} or compression or filtering or interlace:
                raise ValueError('Unsupported PNG dimensions or encoding')
            dimensions = width, height, {0:1, 2:3, 4:2, 6:4}[colour]
        elif kind == b'IDAT':
            if dimensions is None or ended: raise ValueError('Invalid PNG data order')
            compressed.extend(data)
        elif kind == b'IEND':
            if length or end != len(body): raise ValueError('Invalid PNG ending')
            ended = True
        elif kind in {b'acTL', b'fcTL', b'fdAT'} or not kind[0] & 32 or length > 65536:
            raise ValueError('Unsupported PNG extension')
        position = end
    if not dimensions or not ended or not compressed: raise ValueError('Incomplete PNG')
    width, height, channels = dimensions
    expected = height * (1 + width * channels)
    decoder = zlib.decompressobj()
    try:
        raw = decoder.decompress(bytes(compressed), expected + 1)
    except zlib.error as exc:
        raise ValueError('Invalid PNG compression') from exc
    if len(raw) != expected or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
        raise ValueError('Invalid or excessive PNG pixel data')
    if any(raw[index] > 4 for index in range(0, expected, 1 + width * channels)):
        raise ValueError('Invalid PNG row filter')
    return body
