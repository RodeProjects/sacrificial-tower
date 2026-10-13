"""Read-only mesh topology for fast, complete orthographic silhouettes."""
from dataclasses import dataclass,field
from collections import OrderedDict
from threading import Lock
import numpy as np
from cooling_tower.preview.toolpath import PreviewCancelled
from cooling_tower.preview.display_mesh import MeshTopology,build_mesh_topology


def _check_cancel(event):
    if event is not None and event.is_set():raise PreviewCancelled()


@dataclass(frozen=True,slots=True)
class MeshSilhouette:
    source: np.ndarray=field(compare=False,repr=False)
    vertices: np.ndarray
    normals: np.ndarray
    first_edges: np.ndarray
    second_edges: np.ndarray
    first_faces: np.ndarray
    second_faces: np.ndarray
    topology: MeshTopology=field(compare=False,repr=False)
    contour_cache: OrderedDict=field(default_factory=OrderedDict,compare=False,repr=False)
    contour_lock: Lock=field(default_factory=Lock,compare=False,repr=False)

    def contour_edges(self,direction,event=None):
        """Select only front/back transitions; internal mesh edges disappear."""
        _check_cancel(event)
        facing=self.normals@np.asarray(direction) > 0
        first=facing[self.first_faces]
        second=(self.second_faces >= 0)&facing[np.maximum(self.second_faces,0)]
        selected=first != second
        edges=np.where(first[selected,None],self.first_edges[selected],self.second_edges[selected])
        _check_cancel(event)
        return edges


def build_mesh_silhouette(triangles,event=None):
    """Build adjacency once from exact source coordinates in owned memory."""
    _check_cancel(event)
    topology=build_mesh_topology(triangles,event)
    vertices,faces,normals=topology.vertices,topology.faces,topology.normals
    directed=faces[:,(0,1,1,2,2,0)].reshape(-1,2)
    counts,first,second=topology.counts,topology.first,topology.last
    arrays=(vertices,normals,directed[first].copy(),directed[second].copy(),
            first//3,np.where(counts > 1,second//3,-1))
    for array in arrays:array.setflags(write=False)
    return MeshSilhouette(triangles,*arrays,topology)
