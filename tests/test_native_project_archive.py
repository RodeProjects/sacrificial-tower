from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys
import struct
import tempfile
import unittest
import warnings
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cooling_tower.native_project.archive import ArchiveLimits, ProjectArchive, ProjectArchiveError, parse_xml


class NativeArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "neutral.3mf"

    def archive(self, entries):
        with warnings.catch_warnings(), zipfile.ZipFile(self.path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            warnings.simplefilter("ignore", UserWarning)
            for name, value in entries:
                if isinstance(name, str) and "\\" in name:
                    # ZipInfo normally canonicalizes the Windows separator
                    # while *writing*, so construct the hostile name verbatim.
                    entry = zipfile.ZipInfo(name)
                    entry.filename = name
                    name = entry
                archive.writestr(name, value)

    def test_opc_root_and_relative_references_stay_inside_archive(self):
        self.archive([("3D/3dmodel.model", b"<model/>"), ("3D/Objects/part one.model", b"<model/>")])
        with ProjectArchive(self.path) as archive:
            self.assertEqual(archive.xml("3D/3dmodel.model").tag, "model")
            self.assertEqual(archive.relationship_target("_rels/.rels", "/3D/3dmodel.model"), "3D/3dmodel.model")
            self.assertEqual(archive.relationship_target("3D/_rels/3dmodel.model.rels", "Objects/part%20one.model"), "3D/Objects/part one.model")
            for value in ("../../escape", "file:///source.stl", "https://example.invalid/model", "%2e%2e/%2e%2e/escape", "C:/source.stl"):
                with self.subTest(value=value), self.assertRaises(ProjectArchiveError):
                    archive.relationship_target("_rels/.rels", value)

    def test_member_aliases_traversal_devices_and_file_directory_collisions_rejected(self):
        for entries in (
            [("../escape", b"x")], [("/escape", b"x")], [("C:/escape", b"x")],
            [("3D\\model", b"x")], [("NUL", b"x")], [("name.", b"x")],
            [("a", b"x"), ("A", b"x")], [("a", b"x"), ("a", b"x")],
            [("a", b"x"), ("a/b", b"x")],
        ):
            with self.subTest(entries=entries):
                self.archive(entries)
                with self.assertRaises(ProjectArchiveError), ProjectArchive(self.path):
                    pass

    def test_limits_are_checked_before_member_expansion(self):
        self.archive([("metadata.xml", b"x" * 100)])
        for limits in (replace(ArchiveLimits(), member_bytes=99), replace(ArchiveLimits(), members=0),
                       replace(ArchiveLimits(), expanded_bytes=99), replace(ArchiveLimits(), container_bytes=1)):
            with self.subTest(limits=limits), self.assertRaises(ProjectArchiveError), ProjectArchive(self.path, limits=limits):
                pass
        with ProjectArchive(self.path, limits=replace(ArchiveLimits(), metadata_bytes=99)) as archive:
            with self.assertRaises(ProjectArchiveError):
                archive.read("metadata.xml", metadata=True)

    def test_dtd_and_entity_expansion_are_rejected_in_all_xml_encodings(self):
        text = '<!DOCTYPE x [<!ENTITY e "expanded">]><x>&e;</x>'
        for encoding in ("utf-8", "utf-16", "utf-16-be"):
            with self.subTest(encoding=encoding), self.assertRaises(ProjectArchiveError):
                parse_xml(text.encode(encoding))

    def test_metadata_xml_depth_and_node_count_are_bounded(self):
        for text in ('<x>' * 129 + '</x>' * 129, '<r>' + '<x/>' * 250_000 + '</r>'):
            with self.assertRaisesRegex(ProjectArchiveError, 'Strukturgrenze'):
                parse_xml(text.encode())

    def test_directory_limit_and_false_entry_count_rejected_before_zipinfo_creation(self):
        self.archive([("one", b"a"), ("two", b"b")])
        with self.assertRaises(ProjectArchiveError), ProjectArchive(self.path, limits=replace(ArchiveLimits(), directory_bytes=1)):
            pass
        data = bytearray(self.path.read_bytes())
        offset = data.rfind(b"PK\x05\x06")
        struct.pack_into("<HH", data, offset + 8, 1, 1)
        self.path.write_bytes(data)
        with self.assertRaisesRegex(ProjectArchiveError, "Eintragszahl"), ProjectArchive(self.path):
            pass

    def test_external_relationship_is_not_resolved(self):
        self.archive([("_rels/.rels", b'<Relationships><Relationship TargetMode="External" Target="https://example.invalid/part"/></Relationships>')])
        with ProjectArchive(self.path) as archive, self.assertRaises(ProjectArchiveError):
            archive.check_relationships()

    def test_native_export_without_optional_thumbnails_retains_required_model(self):
        self.archive([("3D/3dmodel.model", b"<model/>"), ("_rels/.rels", b'<Relationships><Relationship Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel" Target="/3D/3dmodel.model"/><Relationship Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/thumbnail" Target="/Metadata/plate_1.png"/></Relationships>')])
        with ProjectArchive(self.path) as archive:
            archive.check_relationships()
        self.archive([("_rels/.rels", b'<Relationships><Relationship Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel" Target="/3D/missing.model"/></Relationships>')])
        with ProjectArchive(self.path) as archive, self.assertRaises(ProjectArchiveError):
            archive.check_relationships()

    def test_symlink_and_corrupt_zip_are_rejected(self):
        link = zipfile.ZipInfo("linked.model")
        link.create_system = 3
        link.external_attr = 0o120777 << 16
        self.archive([(link, b"../../original")])
        with self.assertRaises(ProjectArchiveError), ProjectArchive(self.path):
            pass
        self.path.write_bytes(b"not an archive")
        with self.assertRaises(ProjectArchiveError), ProjectArchive(self.path):
            pass

    def test_invalid_utf8_relationship_is_reported_as_archive_error(self):
        self.archive([('3D/model.model',b'<model/>')])
        with ProjectArchive(self.path) as archive:
            with self.assertRaisesRegex(ProjectArchiveError,'UTF-8'):
                archive.relationship_target('_rels/.rels','/3D/%FF.model')

    def test_crc_and_deflate_corruption_in_auxiliary_parts_are_rejected(self):
        for compression in (zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED):
            with self.subTest(compression=compression):
                with zipfile.ZipFile(self.path,'w',compression=compression) as archive:
                    archive.writestr('3D/model.model',b'<model/>')
                    archive.writestr('Metadata/auxiliary.bin',b'neutral auxiliary test data'*20)
                with zipfile.ZipFile(self.path) as archive:
                    offset=archive.getinfo('Metadata/auxiliary.bin').header_offset
                data=bytearray(self.path.read_bytes())
                name_length,extra_length=struct.unpack_from('<HH',data,offset+26)
                position=offset+30+name_length+extra_length
                data[position] = 7 if compression==zipfile.ZIP_DEFLATED else data[position]^1
                self.path.write_bytes(data)
                with ProjectArchive(self.path) as archive:
                    self.assertEqual(archive.xml('3D/model.model').tag,'model')
                    with self.assertRaises(ProjectArchiveError):archive.verify_remaining_members()
                with ProjectArchive(self.path) as archive:
                    with self.assertRaises(ProjectArchiveError):archive.read('Metadata/auxiliary.bin')


if __name__ == "__main__":
    unittest.main()
