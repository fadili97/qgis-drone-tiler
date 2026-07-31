# -*- coding: utf-8 -*-
"""Build EXIF/XMP APP1 segments and inject them into an existing JPEG.

The pixel data is never touched — segments are spliced in, so there is no
re-encoding and no extra generation loss.
"""
import struct

BYTE, ASCII, SHORT, LONG, RATIONAL = 1, 2, 3, 4, 5


def _ascii(s):
    return s.encode('ascii', 'replace') + b'\x00'


def _rational(value, den=10000):
    return struct.pack('<II', int(round(float(value) * den)), den)


def _dms(value):
    """Decimal degrees -> 3 RATIONALs (deg, min, sec)."""
    v = abs(float(value))
    d = int(v)
    m = int((v - d) * 60)
    s = (v - d - m / 60.0) * 3600.0
    return _rational(d, 1) + _rational(m, 1) + _rational(s, 10000)


def _build_ifd(entries, base):
    """entries: list of (tag, type, count, raw_bytes). Returns IFD + its data."""
    n = len(entries)
    data_off = base + 2 + 12 * n + 4
    out = struct.pack('<H', n)
    data = b''
    for tag, typ, count, raw in sorted(entries, key=lambda e: e[0]):
        if len(raw) <= 4:
            val = raw + b'\x00' * (4 - len(raw))
        else:
            val = struct.pack('<I', data_off + len(data))
            data += raw
            if len(data) % 2:
                data += b'\x00'
        out += struct.pack('<HHI', tag, typ, count) + val
    out += struct.pack('<I', 0)
    return out + data


def build_exif(make='DJI', model='M3E', software='Drone Tiler',
               datetime_str=None, lat=None, lon=None, alt=None,
               focal_mm=12.29, focal_35=24, width=None, height=None,
               exposure=0.0025, fnumber=2.8, iso=100):
    """Return a complete APP1 EXIF segment (marker + length included)."""
    ifd0 = [
        (0x010F, ASCII, len(_ascii(make)), _ascii(make)),
        (0x0110, ASCII, len(_ascii(model)), _ascii(model)),
        (0x0112, SHORT, 1, struct.pack('<H', 1)),
        (0x0131, ASCII, len(_ascii(software)), _ascii(software)),
    ]
    if datetime_str:
        ifd0.append((0x0132, ASCII, len(_ascii(datetime_str)), _ascii(datetime_str)))

    exif = [
        (0x829A, RATIONAL, 1, _rational(exposure, 100000)),
        (0x829D, RATIONAL, 1, _rational(fnumber, 100)),
        (0x8827, SHORT, 1, struct.pack('<H', int(iso))),
        (0x920A, RATIONAL, 1, _rational(focal_mm, 100)),
        (0xA405, SHORT, 1, struct.pack('<H', int(focal_35))),
    ]
    if datetime_str:
        exif.append((0x9003, ASCII, len(_ascii(datetime_str)), _ascii(datetime_str)))
        exif.append((0x9004, ASCII, len(_ascii(datetime_str)), _ascii(datetime_str)))
    if width:
        exif.append((0xA002, LONG, 1, struct.pack('<I', int(width))))
    if height:
        exif.append((0xA003, LONG, 1, struct.pack('<I', int(height))))

    gps = []
    if lat is not None and lon is not None:
        gps = [
            (0x0000, BYTE, 4, b'\x02\x03\x00\x00'),
            (0x0001, ASCII, 2, _ascii('N' if lat >= 0 else 'S')),
            (0x0002, RATIONAL, 3, _dms(lat)),
            (0x0003, ASCII, 2, _ascii('E' if lon >= 0 else 'W')),
            (0x0004, RATIONAL, 3, _dms(lon)),
        ]
        if alt is not None:
            gps.append((0x0005, BYTE, 1, b'\x00' if alt >= 0 else b'\x01'))
            gps.append((0x0006, RATIONAL, 1, _rational(abs(alt), 1000)))

    # two passes: sizes are pointer-independent, so offsets stay valid
    def assemble(exif_off, gps_off):
        e = list(ifd0)
        e.append((0x8769, LONG, 1, struct.pack('<I', exif_off)))
        if gps:
            e.append((0x8825, LONG, 1, struct.pack('<I', gps_off)))
        return _build_ifd(e, 8)

    ifd0_bytes = assemble(0, 0)
    exif_off = 8 + len(ifd0_bytes)
    exif_bytes = _build_ifd(exif, exif_off)
    gps_off = exif_off + len(exif_bytes)
    gps_bytes = _build_ifd(gps, gps_off) if gps else b''
    ifd0_bytes = assemble(exif_off, gps_off)

    tiff = b'II' + struct.pack('<HI', 42, 8) + ifd0_bytes + exif_bytes + gps_bytes
    payload = b'Exif\x00\x00' + tiff
    return b'\xff\xe1' + struct.pack('>H', len(payload) + 2) + payload


XMP_TEMPLATE = (
    '<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>'
    '<x:xmpmeta xmlns:x="adobe:ns:meta/">'
    '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
    '<rdf:Description rdf:about="" '
    'xmlns:drone-dji="http://www.dji.com/drone-dji/1.0/" '
    'drone-dji:Version="1.6" '
    'drone-dji:ImageSource="WideCamera" '
    'drone-dji:GpsStatus="Normal" '
    'drone-dji:AltitudeType="GpsFusionAlt" '
    'drone-dji:GpsLatitude="{lat:+.9f}" '
    'drone-dji:GpsLongitude="{lon:+.9f}" '
    'drone-dji:AbsoluteAltitude="{abs_alt:+.3f}" '
    'drone-dji:RelativeAltitude="{rel_alt:+.3f}" '
    'drone-dji:GimbalRollDegree="+0.00" '
    'drone-dji:GimbalYawDegree="{yaw:+.2f}" '
    'drone-dji:GimbalPitchDegree="{pitch:+.2f}" '
    'drone-dji:FlightRollDegree="+0.00" '
    'drone-dji:FlightYawDegree="{yaw:+.2f}" '
    'drone-dji:FlightPitchDegree="+0.00" '
    'drone-dji:SurveyingMode="1" '
    'drone-dji:RtkFlag="0" '
    '/></rdf:RDF></x:xmpmeta><?xpacket end="w"?>'
)


def build_xmp(lat, lon, abs_alt, rel_alt, yaw, pitch=-90.0):
    xml = XMP_TEMPLATE.format(lat=lat, lon=lon, abs_alt=abs_alt,
                              rel_alt=rel_alt, yaw=yaw, pitch=pitch)
    payload = b'http://ns.adobe.com/xap/1.0/\x00' + xml.encode('utf-8')
    return b'\xff\xe1' + struct.pack('>H', len(payload) + 2) + payload


def inject(jpeg, segments):
    """Return `jpeg` with existing APP1 segments replaced by `segments`."""
    if jpeg[:2] != b'\xff\xd8':
        raise ValueError('not a JPEG')
    i = 2
    kept = b''
    while i < len(jpeg) - 1:
        if jpeg[i] != 0xFF:
            break
        marker = jpeg[i + 1]
        if marker == 0xDA:  # start of scan — rest is entropy-coded
            break
        seg_len = struct.unpack('>H', jpeg[i + 2:i + 4])[0]
        if marker != 0xE1:  # drop old APP1 (EXIF/XMP), keep everything else
            kept += jpeg[i:i + 2 + seg_len]
        i += 2 + seg_len
    return b'\xff\xd8' + b''.join(segments) + kept + jpeg[i:]
