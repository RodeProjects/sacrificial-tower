"""Original-object preparation and coalesced rendering for the range editor.

Uses the manual editor's mesh simplification, exact contours, raster/vector
replay and managed render worker. Camera movement only transforms a cached
picture; mesh preparation and expensive color/quality changes run off-thread.
"""
from collections import OrderedDict
from itertools import count
from dataclasses import replace
from types import SimpleNamespace
import traceback

import numpy as np
from PySide6.QtCore import QObject, QTimer, Signal, Slot
from cooling_tower.gui.background_jobs import JobKind
from cooling_tower.gui.worker_contract import CancelableWorker
from cooling_tower.gui.manual_view_worker import ManualViewWorker, SpatialFrame
from cooling_tower.manual.geometry import ManualSettings
from cooling_tower.manual.service import check_cancel
from cooling_tower.preview import PreviewCancelled
from cooling_tower.preview.mesh_silhouette import build_mesh_silhouette


# ManualCanvas uses positive IDs; range windows share a decreasing sequence so
# a closing worker cannot collide with a newly opened editor in the same manager.
_VIEW_REQUEST_IDS = count(-1, -1)


class SourceMeshWorker(CancelableWorker):
    succeeded = Signal(int, object)
    failed = Signal(int, str, str)
    finished = Signal(int)

    def __init__(self, request_id, artifact, reference):
        super().__init__()
        self.request_id, self.artifact, self.reference = request_id, artifact, reference

    @Slot()
    def run(self):
        try:
            import trimesh
            if not self.artifact.matches_current_file(verify_content=True):
                raise ValueError("Die Original-STL wurde seit der Vorbereitung verändert.")
            check_cancel(self.cancellation_event)
            mesh = trimesh.load(self.artifact.original_path, file_type="stl", force="mesh", process=False)
            triangles = np.asarray(mesh.triangles, dtype=float).copy()
            triangles[:, :, 2] -= float(mesh.bounds[0, 2])
            triangles.setflags(write=False)
            topology = build_mesh_silhouette(triangles, self.cancellation_event)
            if not self.artifact.matches_current_file(verify_content=True):
                raise ValueError("Die Original-STL wurde während der Vorschauaufbereitung verändert.")
            check_cancel(self.cancellation_event)
            result = SimpleNamespace(**vars(self.reference))
            result.object_triangles, result.object_silhouette = triangles, topology
        except PreviewCancelled:
            pass
        except Exception as error:
            if not self.cancellation_requested():
                self.failed.emit(self.request_id, str(error), traceback.format_exc())
        else:
            if not self.cancellation_requested():
                self.succeeded.emit(self.request_id, result)
        finally:
            self.finished.emit(self.request_id)


class OriginalObjectView(QObject):
    def __init__(self, canvas, artifact, manager):
        super().__init__(canvas)
        self.canvas, self.manager = canvas, manager
        self.reference = SimpleNamespace(
            context=SimpleNamespace(key=getattr(artifact, "original_sha256", None), layers=canvas.layers),
            silhouette=canvas._silhouette,
            source_data=SimpleNamespace(object_segments=canvas._segments),
            object_triangles=None, object_silhouette=None)
        self.settings = replace(ManualSettings(), critical_layers_enabled=True)
        self.cache = OrderedDict()
        self.job_id = None
        self.request_id = next(_VIEW_REQUEST_IDS)
        self.active_key = None
        self.failed_key = None
        self.closed = False
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(45)
        self.timer.timeout.connect(self._start_render)
        manager.job_released.connect(self._released)
        worker = SourceMeshWorker(self.request_id, artifact, self.reference)
        worker.succeeded.connect(self._mesh_ready)
        worker.failed.connect(self._failed)
        self.job_id = manager.start_job(kind=JobKind.MANUAL_VIEW, request_id=self.request_id, worker=worker,
                                        parent_operation_id="range-original-mesh")

    def key(self):
        return (self.canvas.yaw_deg, self.canvas.target_time_s,
                self.canvas.gradient_start_deficit_s, self.canvas.gradient_full_deficit_s,
                self.canvas.object_resolution_percent)

    def frame(self):
        center = tuple(self.reference.silhouette.center_xy)
        return SpatialFrame(0, 0, 1, (0, 0), 0, 0, center, (0, 0), center,
                            self.canvas.yaw_deg, "both", True)

    def draw(self, painter):
        if self.reference.object_triangles is None:
            return False
        key = self.key()
        picture = self.cache.get(key)
        if picture is None:
            if key != self.failed_key:
                if self.job_id is not None and self.active_key is not None and key != self.active_key:
                    self.manager.cancel_job(self.job_id, reason="range_view_replaced")
                if not self.timer.isActive():
                    self.timer.start()
            return False
        self.cache.move_to_end(key)
        painter.save()
        painter.translate(self.canvas.x_for_position(0), self.canvas.y_for_z(0))
        painter.scale(self.canvas._scale(), self.canvas._scale())
        painter.drawPicture(0, 0, picture)
        painter.restore()
        return True

    def _start_render(self):
        if (self.closed or getattr(self.manager.parent(), "_closing", False)
                or self.job_id is not None or self.reference.object_triangles is None):
            return
        key = self.key()
        if key in self.cache or key == self.failed_key:
            return
        self.request_id = next(_VIEW_REQUEST_IDS)
        self.active_key = key
        settings = replace(self.settings, object_resolution_percent=key[4], color_reference_time_s=key[1],
                           gradient_start_deficit_s=key[2], gradient_full_deficit_s=key[3])
        worker = ManualViewWorker(self.request_id, self.reference, self.frame(), settings, key)
        worker.succeeded.connect(self._rendered)
        worker.failed.connect(self._failed)
        self.job_id = self.manager.start_job(kind=JobKind.MANUAL_VIEW, request_id=self.request_id,
                                             worker=worker, parent_operation_id="range-original-view")

    @Slot(int, object)
    def _mesh_ready(self, request_id, reference):
        if self.closed:
            return
        self.reference = reference
        self.timer.start()

    @Slot(int, object)
    def _rendered(self, request_id, result):
        if self.closed or request_id != self.request_id:
            return
        key, picture = result
        self.cache[key] = picture
        def size(value):
            raster = getattr(value, "raster_size", (0, 0))
            return value.size() + raster[0] * raster[1] * 8
        while len(self.cache) > 10 or (len(self.cache) > 1 and sum(size(p) for p in self.cache.values()) > 32 * 1024 * 1024):
            self.cache.popitem(last=False)
        self.canvas._background = None
        self.canvas.update()

    @Slot(int, str, str)
    def _failed(self, request_id, message, details):
        if self.closed:
            return
        self.failed_key = self.active_key
        self.canvas.setAccessibleDescription("Objektflächen nicht verfügbar: " + message)

    @Slot(object)
    def _released(self, job):
        if job.job_id != self.job_id:
            return
        self.job_id = None
        self.active_key = None
        if not self.closed:
            self.timer.start()

    def close(self):
        self.closed = True
        self.timer.stop()
        if self.job_id is not None:
            self.manager.cancel_job(self.job_id, reason="range_editor_closed")
