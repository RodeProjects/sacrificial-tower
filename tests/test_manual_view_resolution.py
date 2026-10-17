import sys
import unittest
from pathlib import Path
from threading import Event
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
import trimesh
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from PySide6.QtGui import QColor,QImage,QPainter
from cooling_tower.gui import manual_view_worker as rendering
from cooling_tower.gui.design_tokens import ORIGINAL_OBJECT_BLUE,ORIGINAL_OBJECT_TOPOLOGY_DARKENING
from cooling_tower.gui.manual_view_worker import simplify_display_mesh,SpatialFrame
from cooling_tower.manual.geometry import OBJECT_RESOLUTION_STAGES,ManualSettings
from cooling_tower.preview import PreviewCancelled
from cooling_tower.preview.mesh_silhouette import build_mesh_silhouette


class ManualViewResolutionTests(unittest.TestCase):
    def test_shared_topology_has_less_contrast_without_changing_the_surface(self):
        brightness=np.array([.9,1.,1.1])
        standard,indices=rendering.surface_styles(QColor(ORIGINAL_OBJECT_BLUE),brightness,
            topology_darkening=(125,145))
        subdued,subdued_indices=rendering.surface_styles(QColor(ORIGINAL_OBJECT_BLUE),brightness)
        np.testing.assert_array_equal(indices,subdued_indices)
        def difference(first,second):
            return sum(abs(a-b) for a,b in zip(first.getRgb()[:3],second.getRgb()[:3]))
        for (fill,edge,node),(soft_fill,soft_edge,soft_node) in zip(standard,subdued):
            self.assertEqual(fill,soft_fill)
            for normal,soft in ((edge,soft_edge),(node,soft_node)):
                self.assertLess(difference(soft.color(),fill),difference(normal.color(),fill))
                self.assertEqual(soft.widthF(),normal.widthF())
        reference=SimpleNamespace(context=SimpleNamespace(layers=(
            SimpleNamespace(z_mm=1,total_time_s=20),SimpleNamespace(z_mm=2,total_time_s=1))))
        frame=SpatialFrame(240,240,90,(0,90),0,0,(0,0),(0,0),(0,0),0,"both",True)
        settings=replace(ManualSettings(),critical_layers_enabled=True)
        standard,_,backing,contour=rendering.profile_surface_styles(reference,frame,settings,brightness,None,
            topology_darkening=(125,145))
        subdued,_,soft_backing,soft_contour=rendering.profile_surface_styles(reference,frame,settings,brightness,None)
        self.assertEqual(backing,soft_backing)
        self.assertEqual(contour,soft_contour)
        for (fill,edge,_),(soft_fill,soft_edge,_) in zip(standard,subdued):
            self.assertEqual(fill,soft_fill)
            fill_colors=[color for _,color in fill.gradient().stops()]
            for surface,(_,normal),(_,soft) in zip(fill_colors,edge.brush().gradient().stops(),soft_edge.brush().gradient().stops()):
                self.assertLess(difference(soft,surface),difference(normal,surface))

    def test_range_neutral_blue_replaces_time_colors_at_all_quality_stages(self):
        triangles=trimesh.creation.icosphere(subdivisions=2).triangles.copy()
        triangles[:,:,2]+=1
        reference=SimpleNamespace(object_triangles=triangles,object_silhouette=build_mesh_silhouette(triangles),
            object_color=ORIGINAL_OBJECT_BLUE,
            silhouette=SimpleNamespace(center_xy=(0,0),segments_xy=()),
            context=SimpleNamespace(layers=(SimpleNamespace(z_mm=2,total_time_s=0),)))
        frame=SpatialFrame(240,240,90,(0,90),0,0,(0,0),(0,0),(0,0),0,"both",True)
        for stage in OBJECT_RESOLUTION_STAGES:
            settings=replace(ManualSettings(),object_resolution_percent=stage,critical_layers_enabled=False)
            image=rendering.render_spatial_object(reference,frame,settings,None)
            manual_reference=SimpleNamespace(**{key:value for key,value in vars(reference).items() if key!="object_color"})
            manual_image=rendering.render_spatial_object(manual_reference,frame,settings,None)
            self.assertEqual(manual_image,image,stage)
            data=np.frombuffer(image.constBits(),dtype=np.uint8).reshape(240,image.bytesPerLine()//4,4)
            pixels=data[data[:,:,3]>200]
            self.assertGreater(len(pixels),1000,stage)
            self.assertTrue(np.all(pixels[:,0]>pixels[:,2]),stage)
            self.assertTrue(np.all(pixels[:,1]>pixels[:,2]),stage)
            if stage==0:
                self.assertEqual(image.pixelColor(120,120).name(),ORIGINAL_OBJECT_BLUE)
            for xray in (False,True):
                alternate=rendering.render_spatial_object(reference,replace(frame,highlight="object" if xray else "both"),settings,None)
                alpha=alternate.pixelColor(120,120).alpha()
                if xray:self.assertLess(alpha,255)
                else:self.assertEqual(alpha,255)
                self.assertGreater(alpha,0)
            if stage in (0,75):
                picture=rendering.render_spatial_object(reference,frame,settings,None,vector=True)
                faded=QImage(240,240,QImage.Format.Format_ARGB32_Premultiplied);faded.fill(0)
                painter=QPainter(faded);painter.setOpacity(.28)
                painter.drawPicture(0,0,picture);painter.end()
                self.assertLess(faded.pixelColor(120,120).alpha(),255)

    def test_profile_layer_material_keeps_mesh_shading_in_green_and_red_bands(self):
        triangles=trimesh.creation.icosphere(subdivisions=2).triangles.copy()
        triangles[:,:,2]+=1
        triangles.setflags(write=False)
        layers=tuple(SimpleNamespace(z_mm=i/50,total_time_s=20 if i<=50 else 2)
                     for i in range(1,101))
        section=np.array([[[-1,0],[1,0]]])
        reference=SimpleNamespace(object_triangles=triangles,object_silhouette=build_mesh_silhouette(triangles),
            silhouette=SimpleNamespace(center_xy=(0,0),segments_xy=(section,)*len(layers)),
            context=SimpleNamespace(layers=layers))
        frame=SpatialFrame(240,240,90,(0,90),0,0,(0,0),(0,0),(0,0),0,"both",True)
        for rotation,stage in ((angle,stage) for angle in (0,37,90)
                               for stage in OBJECT_RESOLUTION_STAGES[1:]):
            settings=replace(ManualSettings(),object_resolution_percent=stage,critical_layers_enabled=True)
            image=rendering.render_spatial_object(reference,replace(frame,object_rotation=rotation),settings,None)
            data=np.frombuffer(image.constBits(),dtype=np.uint8).reshape(240,image.bytesPerLine()//4,4)
            red=data[50:110,70:170,:3].reshape(-1,3)
            red=red[red[:,2]>red[:,1]*1.6]
            self.assertGreater(len(np.unique(red,axis=0)),10,stage)
            green=data[130:190,70:170,:3].reshape(-1,3)
            green=green[green[:,1]>green[:,2]*1.6]
            self.assertGreater(len(np.unique(green,axis=0)),10,stage)
            self.assertEqual(image.pixelColor(5,5).alpha(),0)
        self.assertFalse(triangles.flags.writeable)

    def test_many_alternating_layer_colors_keep_worker_picture_size_bounded(self):
        triangles=trimesh.creation.icosphere(subdivisions=2).triangles.copy()
        triangles[:,:,2]+=1
        layers=tuple(SimpleNamespace(z_mm=i/500,total_time_s=5 if i%2 else 20)
                     for i in range(1,1001))
        reference=SimpleNamespace(object_triangles=triangles,object_silhouette=build_mesh_silhouette(triangles),
            silhouette=SimpleNamespace(center_xy=(0,0),segments_xy=()),context=SimpleNamespace(layers=layers))
        frame=SpatialFrame(0,0,1,(0,0),0,0,(0,0),(0,0),(0,0),0,"both",True)
        picture=rendering.render_spatial_object(reference,frame,
            replace(ManualSettings(),critical_layers_enabled=True),None,vector=True)
        self.assertIsInstance(picture,rendering.RasterObjectPicture)
        self.assertLess(picture.size()+picture.xray_picture.size(),4*1024*1024)

    def test_dense_profile_material_replays_with_colored_detail_and_open_holes(self):
        mesh=trimesh.creation.torus(major_radius=1,minor_radius=.2,major_sections=128,minor_sections=32)
        mesh.apply_transform(trimesh.transformations.rotation_matrix(np.pi/2,(1,0,0)))
        triangles=mesh.triangles.copy();triangles[:,:,2]+=1.2
        triangles.setflags(write=False)
        layers=tuple(SimpleNamespace(z_mm=i*.024,total_time_s=2) for i in range(1,101))
        section=np.array([[[-1.2,0],[1.2,0]]])
        reference=SimpleNamespace(object_triangles=triangles,object_silhouette=build_mesh_silhouette(triangles),
            silhouette=SimpleNamespace(center_xy=(0,0),segments_xy=(section,)*len(layers)),
            context=SimpleNamespace(layers=layers))
        frame=SpatialFrame(0,0,1,(0,0),0,0,(0,0),(0,0),(0,0),0,"both",True)
        for stage in (1,75,100):
            picture=rendering.render_spatial_object(reference,frame,
                replace(ManualSettings(),object_resolution_percent=stage,critical_layers_enabled=True),None,vector=True)
            self.assertIsInstance(picture,rendering.RasterObjectPicture)
            image=QImage(300,300,QImage.Format.Format_ARGB32_Premultiplied);image.fill(0)
            painter=QPainter(image);painter.translate(150,258);painter.scale(90,90)
            painter.drawPicture(0,0,picture);painter.end()
            self.assertEqual(image.pixelColor(150,150).alpha(),0)
            self.assertGreater(image.pixelColor(240,150).alpha(),200)
            data=np.frombuffer(image.constBits(),dtype=np.uint8).reshape(300,image.bytesPerLine()//4,4)
            red=data[data[:,:,3]>240,:3]
            red=red[red[:,2]>red[:,1]*1.6]
            self.assertGreater(len(np.unique(red,axis=0)),10,stage)

    def test_mesh_backing_is_lighter_transparent_and_xray_applies_consistently(self):
        triangles=trimesh.creation.icosphere(subdivisions=2).triangles
        reference=SimpleNamespace(object_triangles=triangles,object_silhouette=build_mesh_silhouette(triangles),
            silhouette=SimpleNamespace(center_xy=(0,0),segments_xy=()),context=SimpleNamespace(layers=()))
        frame=SpatialFrame(240,240,90,(0,0),0,0,(0,0),(0,0),(0,0),37,"both",True)
        settings=replace(ManualSettings(),object_resolution_percent=1)
        with patch.object(rendering,"simplify_display_mesh",return_value=triangles[:0]):
            plain=rendering.render_spatial_object(reference,frame,settings,None)
            xray=rendering.render_spatial_object(reference,replace(frame,highlight="object"),settings,None)
        backing=plain.pixelColor(120,120)
        self.assertEqual(backing.alpha(),210)
        self.assertGreater(backing.lightness(),QColor(ORIGINAL_OBJECT_BLUE).lightness())
        self.assertAlmostEqual(xray.pixelColor(120,120).alpha()/backing.alpha(),.28,delta=.025)
        solid=rendering.render_spatial_object(reference,frame,replace(settings,object_resolution_percent=0),None)
        self.assertEqual(solid.pixelColor(120,120),QColor(ORIGINAL_OBJECT_BLUE))

    def test_exact_silhouette_keeps_full_bounds_at_all_mesh_stages_and_rotations(self):
        triangles=trimesh.creation.icosphere(subdivisions=3).triangles.copy()
        triangles*=np.array((1.3,.7,1.1))
        triangles.setflags(write=False)
        reference=SimpleNamespace(object_triangles=triangles,object_silhouette=build_mesh_silhouette(triangles),
            silhouette=SimpleNamespace(center_xy=(0,0),segments_xy=()),context=SimpleNamespace(layers=()))
        def bounds(image):
            data=np.frombuffer(image.constBits(),dtype=np.uint8).reshape(image.height(),image.bytesPerLine()//4,4)
            ys,xs=np.nonzero(data[:,:,3])
            return np.array((xs.min(),ys.min(),xs.max(),ys.max()))
        for yaw,pitch in ((0,0),(90,0),(0,90),(0,-90),(-35,25),(72,-18)):
            previous=None
            for rotation in (0,37,90):
                frame=SpatialFrame(300,300,90,(0,0),yaw,pitch,(0,0),(0,0),(0,0),rotation,"both",True)
                full=rendering.render_spatial_object(reference,frame,replace(ManualSettings(),object_resolution_percent=0),None)
                expected=bounds(full)
                if previous is not None and pitch==0:self.assertFalse(np.array_equal(previous,expected))
                previous=expected
                for percent in OBJECT_RESOLUTION_STAGES[1:]:
                    image=rendering.render_spatial_object(reference,frame,replace(ManualSettings(),object_resolution_percent=percent),None)
                    np.testing.assert_allclose(bounds(image),expected,atol=1)
                    self.assertNotEqual(image.pixelColor(150,150),QColor(ORIGINAL_OBJECT_BLUE))
        self.assertFalse(triangles.flags.writeable)

    def test_silhouette_clips_coarse_surfaces_out_of_holes_including_free_view(self):
        triangles=trimesh.creation.annulus(r_min=.4,r_max=1,height=1,sections=96).triangles
        reference=SimpleNamespace(object_triangles=triangles,object_silhouette=build_mesh_silhouette(triangles),
            silhouette=SimpleNamespace(center_xy=(0,0),segments_xy=()),context=SimpleNamespace(layers=()))
        frame=SpatialFrame(240,240,90,(0,0),0,90,(0,0),(0,0),(0,0),37,"both",True)
        settings=replace(ManualSettings(),object_resolution_percent=5)
        with patch.object(rendering,"simplify_display_mesh",return_value=trimesh.creation.box(extents=(2,2,1)).triangles):
            image=rendering.render_spatial_object(reference,frame,settings,None)
        self.assertEqual(image.pixelColor(120,120).alpha(),0)
        self.assertGreater(image.pixelColor(180,120).alpha(),0)
        free=replace(frame,pitch=25,yaw=-35)
        with patch.object(rendering,"original_silhouette_path",wraps=rendering.original_silhouette_path) as contour:
            rendering.render_spatial_object(reference,free,settings,None)
        contour.assert_called_once()

    def test_reused_styles_keep_identical_colors_edges_and_transparent_pixels(self):
        brightness=np.linspace(.86,1.14,5120)
        color=QColor(ORIGINAL_OBJECT_BLUE)
        styles,indices=rendering.surface_styles(color,brightness)
        self.assertLess(len(styles),200)
        for index,value in enumerate(brightness):
            fill,edge,node=styles[indices[index]]
            self.assertEqual(fill,rendering.shaded_color(color,value))
            self.assertEqual(edge.color(),fill.darker(ORIGINAL_OBJECT_TOPOLOGY_DARKENING[0]))
            self.assertEqual(node.color(),fill.darker(ORIGINAL_OBJECT_TOPOLOGY_DARKENING[1]))
            self.assertTrue(edge.isCosmetic())
            self.assertTrue(node.isCosmetic())
            self.assertEqual(edge.widthF(),.5)
            self.assertEqual(node.widthF(),.5)
        reference=SimpleNamespace(object_triangles=trimesh.creation.icosphere(subdivisions=2).triangles,
            silhouette=SimpleNamespace(center_xy=(0,0),segments_xy=(np.array([[[-.5,0],[.5,0]]]),)),
            context=SimpleNamespace(layers=(SimpleNamespace(z_mm=.2,total_time_s=1),)))
        frame=SpatialFrame(240,240,90,(0,0),-35,25,(0,0),(0,0),(0,0),37,"both")
        original=rendering.draw_surface
        def legacy(painter,polygon,color,brightness,style=None):
            palette,_=rendering.surface_styles(color,np.array([brightness]))
            original(painter,polygon,color,brightness,palette[0])
        profile_styles,_,_,contour=rendering.profile_surface_styles(reference,frame,
            replace(ManualSettings(),critical_layers_enabled=True),brightness[:3],None)
        self.assertEqual(contour.widthF(),1)
        for _,edge,node in profile_styles:
            self.assertEqual(edge.widthF(),.5)
            self.assertEqual(node.widthF(),.5)
        for critical in (False,True):
            settings=replace(ManualSettings(),object_resolution_percent=100,critical_layers_enabled=critical)
            for highlight in ("both","object","all"):
                current=replace(frame,highlight=highlight)
                with patch.object(rendering,"draw_surface",side_effect=legacy):
                    expected=rendering.render_spatial_object(reference,current,settings,None)
                actual=rendering.render_spatial_object(reference,current,settings,None)
                self.assertEqual(actual,expected)

    def test_all_stages_reduce_complete_surfaces_without_mutating_source(self):
        source=trimesh.creation.icosphere(subdivisions=5).triangles.copy()
        original=source.copy();source.setflags(write=False)
        counts=[]
        for percent in OBJECT_RESOLUTION_STAGES[1:]:
            reduced=simplify_display_mesh(source,percent)
            counts.append(len(reduced))
            mesh=trimesh.Trimesh(vertices=reduced.reshape(-1,3),
                faces=np.arange(len(reduced)*3).reshape(-1,3),process=True)
            self.assertTrue(mesh.is_watertight)
            self.assertTrue(np.isfinite(reduced).all())
            np.testing.assert_allclose(reduced.min(axis=(0,1)),source.min(axis=(0,1)),atol=.042)
            np.testing.assert_allclose(reduced.max(axis=(0,1)),source.max(axis=(0,1)),atol=.042)
        self.assertEqual(counts,sorted(counts))
        self.assertLessEqual(counts[0],len(source)*.8)
        self.assertGreater(counts[0],len(source)*.25)
        np.testing.assert_array_equal(source,original)

    def test_small_or_degenerate_sources_and_cancelled_reduction(self):
        small=trimesh.creation.box().triangles
        self.assertIs(simplify_display_mesh(small,10),small)
        degenerate=np.zeros((100,3,3))
        self.assertIs(simplify_display_mesh(degenerate,50),degenerate)
        event=Event();event.set()
        with self.assertRaises(PreviewCancelled):
            simplify_display_mesh(trimesh.creation.icosphere(subdivisions=2).triangles,50,event)

    def test_zero_draws_exact_flat_contours_without_simplification_or_surface_details(self):
        triangles=trimesh.creation.icosphere(subdivisions=4).triangles.copy()
        original=triangles.copy();triangles.setflags(write=False)
        topology=build_mesh_silhouette(triangles)
        reference=SimpleNamespace(object_triangles=triangles,object_silhouette=topology,
            silhouette=SimpleNamespace(center_xy=(0,0),segments_xy=()),context=SimpleNamespace(layers=()))
        settings=replace(ManualSettings(),object_resolution_percent=0)
        for yaw,pitch,rotation in ((0,0,0),(-35,25,37),(90,90,0),(0,-90,180)):
            frame=SpatialFrame(240,240,90,(0,0),yaw,pitch,(0,0),(0,0),(0,0),rotation,"both")
            with patch.object(rendering,"simplify_display_mesh",side_effect=AssertionError("mesh reduction")),\
                 patch.object(rendering,"draw_surface",side_effect=AssertionError("mesh details")),\
                 patch.object(rendering,"build_mesh_silhouette",side_effect=AssertionError("topology rebuilt")):
                image=rendering.render_spatial_object(reference,frame,settings,None)
            self.assertEqual(image.pixelColor(120,120),QColor(ORIGINAL_OBJECT_BLUE))
            self.assertEqual(image.pixelColor(5,5).alpha(),0)
            self.assertLess(len(topology.contour_edges((0,0,1))),len(triangles)//20)
        np.testing.assert_array_equal(triangles,original)
        self.assertFalse(topology.vertices.flags.writeable)
        event=Event();event.set()
        with self.assertRaises(PreviewCancelled):build_mesh_silhouette(triangles,event)

    def test_zero_silhouette_preserves_holes_in_full_resolution_top_view(self):
        triangles=trimesh.creation.annulus(r_min=.4,r_max=1,height=1,sections=96).triangles
        reference=SimpleNamespace(object_triangles=triangles,object_silhouette=build_mesh_silhouette(triangles),
            silhouette=SimpleNamespace(center_xy=(0,0),segments_xy=()),context=SimpleNamespace(layers=()))
        frame=SpatialFrame(240,240,90,(0,0),0,90,(0,0),(0,0),(0,0),0,"both")
        image=rendering.render_spatial_object(reference,frame,replace(ManualSettings(),object_resolution_percent=0),None)
        self.assertEqual(image.pixelColor(120,120).alpha(),0)
        self.assertEqual(image.pixelColor(180,120),QColor(ORIGINAL_OBJECT_BLUE))

    def test_zero_profile_silhouette_keeps_disconnected_islands_and_layer_colors(self):
        pieces=[]
        for center in (-.75,.75):
            mesh=trimesh.creation.box(extents=(.5,.5,1));mesh.apply_translation((center,0,.5))
            pieces.append(mesh.triangles)
        triangles=np.concatenate(pieces)
        section=np.array([[[-1,0],[-.5,0]],[[.5,0],[1,0]]])
        reference=SimpleNamespace(object_triangles=triangles,object_silhouette=build_mesh_silhouette(triangles),
            silhouette=SimpleNamespace(center_xy=(0,0),segments_xy=(section,section)),
            context=SimpleNamespace(layers=(SimpleNamespace(z_mm=.5,total_time_s=20),SimpleNamespace(z_mm=1,total_time_s=2))))
        frame=SpatialFrame(240,240,60,(0,0),0,0,(0,0),(0,0),(0,0),0,"both")
        settings=replace(ManualSettings(),object_resolution_percent=0,critical_layers_enabled=True)
        image=rendering.render_spatial_object(reference,frame,settings,None)
        self.assertEqual(image.pixelColor(165,105),QColor(rendering.LayerRangeCanvas.OBJECT_COLOR))
        self.assertEqual(image.pixelColor(165,75),QColor(rendering.LayerRangeCanvas.CRITICAL_COLOR))
        self.assertEqual(image.pixelColor(120,105).alpha(),0)

    def test_non_manifold_silhouette_matches_union_without_inventing_connections_or_clipping_faces(self):
        # Open, irregularly wound shells, with one overused edge. The source
        # triangle projection is the reference even when closed contours fail.
        pieces=[]
        for x in (-1,1):
            mesh=trimesh.creation.box(extents=(.6,.6,1))
            mesh.apply_translation((x,0,0))
            triangles=mesh.triangles.copy()[1:]
            triangles[::2]=triangles[::2,::-1]
            pieces.extend((triangles,triangles[:1]))
        triangles=np.concatenate(pieces)
        topology=build_mesh_silhouette(triangles)
        self.assertFalse(topology.topology.reliable_contours)
        reference=SimpleNamespace(object_triangles=triangles,object_silhouette=topology,
            silhouette=SimpleNamespace(center_xy=(0,0),segments_xy=()),context=SimpleNamespace(layers=()))
        for yaw,pitch in ((0,0),(-35,25),(0,90)):
            frame=SpatialFrame(300,240,65,(0,0),yaw,pitch,(0,0),(0,0),(0,0),0,"both",True)
            silhouette=rendering.render_spatial_object(reference,frame,replace(ManualSettings(),object_resolution_percent=0),None)
            image=rendering.render_spatial_object(reference,frame,replace(ManualSettings(),object_resolution_percent=1),None)
            for original,result in zip(np.frombuffer(silhouette.constBits(),dtype=np.uint8).reshape(-1,4),
                                       np.frombuffer(image.constBits(),dtype=np.uint8).reshape(-1,4)):
                if original[3]:self.assertGreater(result[3],0)
            self.assertEqual(image.pixelColor(150,120).alpha(),0)
        np.testing.assert_array_equal(triangles,np.concatenate(pieces))
