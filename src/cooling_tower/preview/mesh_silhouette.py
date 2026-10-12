"""Read-only mesh topology for fast, complete orthographic silhouettes."""
from dataclasses import dataclass,field
import numpy as np
from cooling_tower.preview.toolpath import PreviewCancelled


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
    vertices,inverse=np.unique(np.asarray(triangles).reshape(-1,3),axis=0,return_inverse=True)
    _check_cancel(event)
    faces=inverse.reshape(-1,3)
    normals=np.cross(triangles[:,1]-triangles[:,0],triangles[:,2]-triangles[:,0])
    directed=faces[:,(0,1,1,2,2,0)].reshape(-1,2)
    _,groups,counts=np.unique(np.sort(directed,axis=1),axis=0,return_inverse=True,return_counts=True)
    _check_cancel(event)
    order=np.argsort(groups,kind="stable")
    starts=np.cumsum(counts)-counts
    first=order[starts]
    second=order[starts+counts-1]
    arrays=(vertices,normals,directed[first].copy(),directed[second].copy(),
            first//3,np.where(counts > 1,second//3,-1))
    for array in arrays:array.setflags(write=False)
    return MeshSilhouette(triangles,*arrays)
