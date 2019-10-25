'''
Image Registration of Channels for multi-rounds

Author: Rebecca LI, University of Houston, Farsight Lab, 2019
xiaoyang.rebecca.li@gmail.com

--- inspired  from ---
# https://github.com/scikit-image/skimage-tutorials/blob/master/lectures/adv3_panorama-stitching.ipynb
Improvements compared to above 
1) featureExtract_tiled (specifically for texture based large scale images)
2) support multiprocess & single thread
3) reuse of extracted feature in first rounds to the rest

--- conda packages ---
conda install -c conda-forge scikit-image \
conda install scikit-learn \
conda install -c conda-forge tifffile 

--- e.g. ---
&python registration_multiRds.py \
    -i [inputPath] \
    -o [outputPath]
'''

import os
import re
import sys
import time
import numpy as np
import shutil
import skimage,cv2
from skimage.color import rgb2gray
from skimage.feature import ORB, match_descriptors
from skimage import exposure,io,segmentation,img_as_ubyte,img_as_uint,measure,morphology   
from skimage.transform import warp, ProjectiveTransform, SimilarityTransform, AffineTransform,PolynomialTransform,resize
from skimage.filters import threshold_otsu

import matplotlib.pyplot as plt
import tifffile as tiff
import multiprocessing
from multiprocessing.pool import ThreadPool
import warnings
warnings.filterwarnings("ignore")
import argparse

from sklearn.neighbors import DistanceMetric

import tiled_mp_fcts as mpfcts
import vis_fcts as visfcts
from ransac_tile import ransac_tile
from ransac_lls import ransac_lls

#import matplotlib.pyplot as plt
parser = argparse.ArgumentParser(description='***  Whole brain segentation pipeline on DAPI + Histone Channel ***'
                                             + '\ne.g\n'
                                             + '\t$ python3 registrationORB_RANSIC.py  # run on whole brain \n '
                                             + '\t$ python3 registrationORB_RANSIC.py -t T  '
                                             + '-i /data/jjahanip/50_plex/stitched  '
                                             + '-w /data/xiaoyang/CHN50/Registered_Rebecca',
                                 formatter_class=argparse.RawTextHelpFormatter)

parser.add_argument('-d', '--demo', default='F', type=str,
                    help=" 'T' only match channel 0, 'F' match all channels")
parser.add_argument('-i', '--input_dir', 
                    default=r"D:\research in lab\dataset\50CHN\registration_demo\before",
                    help='Path to the directory of input images')
parser.add_argument('-o', '--output_dir',
                    default=r"D:\research in lab\dataset\50CHN\registration_demo\after",
                    help='Path to the directory to save output images')
parser.add_argument('-ot', '--outputType', required=False, default="16bit", type=str,
                    help='Save tif image type: "8bit" or "16bit"')
parser.add_argument('-it', '--inputType', required=False, default="16bit", type=str,
                    help='Save tif image type: "8bit" or "16bit"')
parser.add_argument('-nk', '--nKeypoint', required=False, default=300000, type=int,
                    help=" nKeypoint ")
parser.add_argument('-kp_path', '--keypoint_dir', 
                    default= None,
                    help='Path to the directory to read the extracted keypoins')
parser.add_argument('-mt', '--maxtrials', required=False, default=5000, type=int,
                    help=" max_trials ")
parser.add_argument('-mp', '--multiprocess', required=False, default="T", type=str,
                    help=" 'T' multi processing, 'F' single processing")
parser.add_argument('--imadjust', required=False, default = 'F',type = str, 
                        help='whether to adjust the image for feature extraction')    
parser.add_argument('--targetRound', required=False, default='R2', type=str,
                    help="keyword for target round")        
# the smaller the tilling, longer the time, better the results
parser.add_argument('-t', '--tiling', required=False, default="1000,1000", type=str,
                    help=" 'tiling_r, tilling_r' or '[]' or None, for 'user specified tiling shape', 'no tilling',or default ")

args = parser.parse_args()

#%%
def log(text, array=None):
    """Prints a text message. And, optionally, if a Numpy array is provided it
    prints it's shape, min, and max values.
    """
    if array is not None:
        text = text.ljust(25)
        if type(array) == dict:
            text += ("dictionary len = " + len(array))
            for key in list(array.keys()):
                item = array[key]
                text += (" key = " + key + " \titem.shape= " + item.shape)
                text += (" min: {:10.5f}  max: {:10.5f}".format(item.min(), item.max()))
        else:
            text = text.ljust(25)
            text += ("shape: {:20}  ".format(str(array.shape)))
            if array.size:
                text += ("min: {:10.5f}  max: {:10.5f}".format(array.min(), array.max()))
            else:
                text += ("min: {:10}  max: {:10}".exiformat("", ""))
            text += "  {}".format(array.dtype)
    print(text)


class Paras(object):
    def __init__(self):
        # Parameters for ORB
        self.n_keypoints = 300000
        self.fast_threshold = 0.08
        self.harris_k = 0.1

        # Parameters for skimage.measure.ransac
        self.min_samples = 5
        self.residual_threshold = 5  # default =1, 7
        self.max_trials = 600
        self.random_state = 42 #230

        # other user defined paras:
        self.target_shape = (4000,8000)
        self.tile_shape = (400, 800)        
        self.multiprocessing = False
        self.ck_shift = 100  # check window dilation width for seaching robust keypoint   # 50
        self.crop_overlap = 10  
        self.err_thres = 1.5
        self.keypoint_dir = None
        self.demo = False
        

    def set_n_keypoints(self, n_keypoints):
        self.n_keypoints = n_keypoints

    def set_max_trials(self, max_trials):
        self.max_trials = max_trials

    def multiprocess(self, multiprocess):
        self.multiprocess = multiprocess

    def set_tile_shape(self, tile_shape):
        self.tile_shape = tile_shape

    def display(self):
        print("============================\n")
        print("Parameters for ORB : ")
        print("\tn_keypoints = ", self.n_keypoints)
        print("\tfast_threshold = ", self.fast_threshold)
        print("\tharris_k = ", self.harris_k)
        print("Parameters for skimage.measure.ransac : ")
        print("\tmin_samples = ", self.min_samples)
        print("\tresidual_threshold = ", self.residual_threshold)
        print("\tmax_trials = ", self.max_trials)
        print("\trandom_state = ", self.random_state)
        print("other user defined paras: ")
        print("\ttile_shape = ", self.tile_shape)
        print("\tmultiprocess = ", self.multiprocess)
        print("\ttarget_shape = ", self.target_shape)
        print("\tck_shift = ", self.ck_shift)
        print("\tcrop_overlap = ", self.crop_overlap)
        print("\tkeypoint_dir = ", self.keypoint_dir)

def spl_tiled_data (data, tileRange_ls ,paras):
    spl_tile_ls = []
    spl_tile_dic ={}
    target_shape = max(tileRange_ls ) [2:]
    keypoints0,keypoints1 = data
    for t_i, tileRange in enumerate( tileRange_ls):
        ck_tileRange=  [ max( 0 , tileRange[0] - paras.ck_shift ), 
                         max( 0 , tileRange[1] - paras.ck_shift ),
                         min( int(target_shape[0] ) -1, tileRange[2] + paras.ck_shift) , 
                         min( int(target_shape[1] ) -1, tileRange[3] + paras.ck_shift) ]         # extract the labels of subpicious window from previous merged results
        bin_kp  = ( keypoints1[:,0] >= tileRange[0] ) * ( keypoints1[:,0] <= tileRange[2] )
        bin_kp *= ( keypoints1[:,1] >= tileRange[1] ) * ( keypoints1[:,1] <= tileRange[3] )         
        bin_kp  = ( keypoints0[:,1] >= ck_tileRange[0] ) * ( keypoints0[:,1] <= ck_tileRange[2] )
        bin_kp *= ( keypoints0[:,0] >= ck_tileRange[1] ) * ( keypoints0[:,0] <= ck_tileRange[3] ) 
        ids_bin_kep  =  np.where(bin_kp)[0]        
        spl_tile_dic[t_i] = ids_bin_kep
        if len(ids_bin_kep) > paras.min_samples /2:           # number of keypoints in this tile have to be bigger than 
            spl_tile_ls.append(ids_bin_kep)    
    return  spl_tile_ls,spl_tile_dic


def mini_register(target,source,paras,
                  keypoints0=None,descriptors0 =None,keypoints1 = None,descriptors1 = None):
    print ("\n#### mini_register")   
    print ( "target.type= ", target.dtype)
    
    model_robust01 = None    # initailze to none
    inliers = None
    src = np.zeros((0,2))
    dst = np.zeros((0,2))
       
    if keypoints0 is None or keypoints1 is None :
        
        orb0 = ORB(n_keypoints = paras.n_keypoints,
                    fast_threshold = paras.fast_threshold,
                    harris_k = paras.harris_k)
        #  if without this step, orb.detect_and_extract will return error        
        orb0.detect(source)
        orb1 = ORB(n_keypoints = paras.n_keypoints,
                    fast_threshold = paras.fast_threshold,
                    harris_k = paras.harris_k)   
        orb1.detect(target)                        # n by 256 array       
        
        print ( "Detected keypoins: len(orb0.scales)= ",len(orb0.scales), "len(orb1.scales)= ",len(orb1.scales))    
        if  len(orb0.scales) > paras.min_samples and len(orb1.scales) > paras.min_samples:
            orb0.detect_and_extract(source)
            keypoints0 = orb0.keypoints  # n by 2 array, n is number of keypoints
            descriptors0 = orb0.descriptors                                        # n by 256 array
            orb1.detect_and_extract(target)
            keypoints1 = orb1.keypoints  # n by 2 array, n is number of keypoints
            descriptors1 = orb1.descriptors                
    
            matches01 = match_descriptors(descriptors0, descriptors1, metric ='hamming' , cross_check=True)
            # sort the matched points according to the distance
            src = keypoints0[matches01[:, 0]][:, ::-1]   # (image to be registered) 
            dst = keypoints1[matches01[:, 1]][:, ::-1]   #  (reference image, target)     
            
    elif keypoints0.shape[0] > paras.min_samples and  keypoints1.shape[0] > paras.min_samples :
        print ( "ReUsed keypoints = ", keypoints0.shape ,keypoints1.shape)
        matches01 = match_descriptors(descriptors0, descriptors1, metric ='hamming' , cross_check=True)
        # sort the matched points according to the distance
        src = keypoints0[matches01[:, 0]][:, ::-1]   # (image to be registered) 
        dst = keypoints1[matches01[:, 1]][:, ::-1]   #  (reference image, target)         
    
    print ("Matched keypoins = ", src.shape[0] )          
    if src.shape[0] > paras.min_samples:
        kps = (src, dst)                 
       
        model_robust01, inliers = skimage.measure.ransac(kps, ProjectiveTransform,
                                                    min_samples         = paras.min_samples, 
                                                    residual_threshold  = paras.residual_threshold,
                                                    max_trials          = paras.max_trials,
                                                    random_state        = paras.random_state,
                                                    ) 
        print ("\t Inital inliers%  =" , ( inliers.sum()/len(inliers)) *100 )

        exam_tileRange_ls    = visfcts.crop_tiles(  ( target.shape[0],target.shape[1] ),
                                           ( int(paras.tile_shape[0]/2), int(paras.tile_shape[1]/2)),
                                                   paras.crop_overlap)  
        spl_tile_ls, spl_tile_dic = spl_tiled_data ( kps , exam_tileRange_ls, paras)

        model_robust01, inliers = ransac_tile(kps, AffineTransform,
                                                    min_samples         = paras.min_samples, 
                                                    residual_threshold  = paras.residual_threshold,
                                                    max_trials          = paras.max_trials,
                                                    random_state        = paras.random_state,
                                                    spl_tile_ls = spl_tile_ls)      
        print ("\t Final inliers%  =" , ( inliers.sum()/len(inliers)) *100 )
        
    if inliers is not None:
        print ("\t min-inliers%  =" , ( inliers.sum()/len(inliers)) *100 )
    else:
        model_robust01 = None # Registration failed, not remove 

    return model_robust01
    

def select_keypointsInMask(kp, binmask):
    # kp = N by 2
    # binmask is same size as image, 1
    selected_kp = np.zeros(kp.shape[0], dtype = np.bool)
    for i, (x, y) in enumerate( zip( kp[:,0],kp[:,1]) ) :
        if binmask[int(x),int(y)] > 0:
            selected_kp[i] = True                 
    return selected_kp



def registrationORB_tiled(targets, sources, paras, write_path, output_type="16bit", input_type="16bit",
                          save_target=True, 
                          keypoints1=None, descriptors1=None, imadjust = False, verbose =0):
    #%%
#    source =  ["D:\research in lab\dataset\50CHN\registration_demo\before\R1C1.tif"]
#    target0 = ["D:\research in lab\dataset\50CHN\registration_demo\before\R2C1.tif"]
#    self.tile_shape = (400, 800)  
    
    #%%
    t_0 = time.time()
    
    target0 = []  # only use target 0 and source 0 for keypoint extraction
    source0 = []
    print("imadjust =",imadjust)
    
    # READING IMAGES
    for key_id, t_key in enumerate( sorted ( targets.keys() )) :                
        # if "C0" in t_key:
        if key_id == 0:
            target0 = tiff.imread(targets[t_key])
            target0 = rgb2gray(target0) if target0.ndim == 3 else target0
            print("Process ", t_key, " as target0", "target0.shape = ", target0.shape)
            target0_key = t_key
    for key_id, s_key in enumerate( sorted ( sources.keys() )) :
        # if "C0" in s_key:
        if key_id == 0:
            source0 = tiff.imread(sources[s_key])
            source0 = rgb2gray(source0) if source0.ndim == 3 else source0
            print("Process ", s_key, " as source0", "source0.shape =", source0.shape)
            source0_key = s_key

    if target0 is [] or source0 is []:
        print("!! target or source not found error:", sys.exc_info()[0])

    '''1. Feature detection and matching'''
    target0 = img_as_ubyte(target0) if input_type is "8bit" else target0
    source0 = img_as_ubyte(source0) if input_type is "8bit" else source0

    target0 = visfcts.adjust_image (target0) if imadjust is True  else target0
    source0 = visfcts.adjust_image (source0) if imadjust is True else source0
    paras.target_shape = ( target0.shape[0],target0.shape[1] )
    
    paras.display()
    target0_mean = target0.mean()
    source0 = visfcts.check_shape(source0,paras.target_shape)                        

    t_8bit = time.time()
    
    # set tile ranges list 
    if paras.tile_shape == []:  # do not apply any tilling
        tile_shape = (int(target0.shape[0]), int(target0.shape[1]))
    else:  # default tile shape is 400*800
        tile_shape = paras.tile_shape
    tile_width, tile_height    = tile_shape
    img_rows = int(target0.shape[0])
    img_cols = int(target0.shape[1])                    

    tileRange_ls    = visfcts.crop_tiles(  ( img_rows,img_cols ),
                                           ( tile_width, tile_width),
                                           paras.crop_overlap)  
    paras.tiles_numbers = len(tileRange_ls)

    if verbose == 1 : 
        print ("tile_shape=" ,tile_shape)
        print("number of the tiles = ", paras.tiles_numbers)
        print("tileRange_ls[0] = ", tileRange_ls[0] )

    # EXTRACT KEYPOINTS
    if paras.keypoint_dir == None:
        keypoints0, descriptors0 = mpfcts.featureExtract_tiled(source0, paras, tileRange_ls)  # keypoints0.max(axis=1)
        if keypoints1 is None or descriptors1 is None:  # need to create featureExtraction for target, else read the created one from input
            keypoints1, descriptors1 = mpfcts.featureExtract_tiled(target0, paras, tileRange_ls)
        
        if paras.demo ==True:
            np.save( os.path.join ( write_path, source0_key.split(".")[0] + "_keypoints0.npy"),keypoints0)
            np.save( os.path.join ( write_path, source0_key.split(".")[0] + "_descriptors0.npy"),descriptors0)
            np.save( os.path.join ( write_path, target0_key.split(".")[0] + "_keypoints1.npy"),keypoints1)
            np.save( os.path.join ( write_path, target0_key.split(".")[0] + "_descriptors1.npy"),descriptors1)   
            print ("EXTRACT KEYPOINTS have been saved")
    else:
        keypoints0 = np.load( os.path.join ( paras.keypoint_dir, source0_key.split(".")[0] + "_keypoints0.npy"))
        descriptors0 = np.load( os.path.join ( paras.keypoint_dir, source0_key.split(".")[0] + "_descriptors0.npy"))
        keypoints1= np.load( os.path.join ( paras.keypoint_dir, target0_key.split(".")[0] + "_keypoints1.npy"))
        descriptors1 = np.load( os.path.join ( paras.keypoint_dir, target0_key.split(".")[0] + "_descriptors1.npy"))    
        print ("EXTRACT KEYPOINTS have been load from path")

    t_featureExtract_tiled = time.time()
    print("[Timer] featureExtract tiled used time (h) =", str((t_featureExtract_tiled - t_8bit) / 3600))
    
    # Match descriptors between target and source image
    if paras.multiprocessing == False:
        src,dst =  mpfcts.match_descriptors_tiled(keypoints0,descriptors0,
                                          keypoints1,descriptors1, 
                                          paras, tileRange_ls ,
                                          ck_shift = paras.ck_shift)
    else:
        src,dst =  mpfcts.transfromest_tiled (keypoints0,descriptors0,
                                          keypoints1,descriptors1, 
                                          paras, tileRange_ls ,
                                          ck_shift = paras.ck_shift)

    ''' 2. Transform estimation ''' 
#    print ("match_descriptors:", src.shape)  # N * 2
#    plt.figure()
#    plt.scatter(src[:,0] ,src[:,1] ,"r")
#    plt.scatter(dst[:,0] ,dst[:,1] ,"g")
    kps = (src, dst)
#    model_robust01, inliers = skimage.measure.ransac( kps, ProjectiveTransform,
#                                                min_samples         = paras.min_samples, 
#                                                residual_threshold  = paras.residual_threshold,
#                                                max_trials          = paras.max_trials,
#                                                random_state        = paras.random_state,
#                                                )
#    print ("\t Inital inliers%  =" , ( inliers.sum()/len(inliers)) *100 )

#%%
  
    exam_tileRange_ls    = visfcts.crop_tiles(  ( img_rows,img_cols ),
                                                ( int( tile_height/2), int( tile_width/2)))  
    

    spl_tile_ls, spl_tile_dic = spl_tiled_data ( kps , exam_tileRange_ls, paras)
   
    model_robust01, inliers = ransac_tile(kps, AffineTransform,
                                                min_samples         = paras.min_samples, 
                                                residual_threshold  = paras.residual_threshold,
                                                max_trials          = paras.max_trials,
                                                random_state        = paras.random_state,
                                                spl_tile_ls         = spl_tile_ls)      
    print ("\t Final inliers%  =" , ( inliers.sum()/len(inliers)) *100 )
    
    ''' 3. Image Warping'''
    # we must warp, or transform, two of the three images so they will properly align with the stationary image.
    
    # Apply same offset on all rest images       
    model_mini_dic = {}
    save_vis = True if paras.demo == True else False
    reuse_kp = False    # whether to reused keypoint for bootstrap region (not recommend, fast but poor align)
    bootstrap = True    # bootstrap on potential folded regions 

    for s_i, source_key in enumerate( sorted ( sources.keys() )) :
        # if "C0" in s_key:
        source = tiff.imread(sources[source_key])
        source = rgb2gray(source) if source.ndim == 3 else source               # uint16
        
        source = visfcts.check_shape(source,paras.target_shape)                        
        source_warped = warp(source, inverse_map = model_robust01.inverse, 
                                 output_shape = paras.target_shape)             # float64
                             
        # rerun the registration for bootstrap regions
        
        if s_i == 0:                                      
            # merge diff regions

            __, inital_diff,binary_target,error,error_map = visfcts.eval_draw_diff ( img_as_ubyte(target0),                                                            
                                                                          img_as_ubyte(source) , exam_tileRange_ls)                   
            if save_vis== True:
                error_map_resized = resize(error_map, (error_map.shape[0]  // 2 , error_map.shape[1] // 2) ,
                                                        mode = "constant")            
                io.imsave(os.path.join(write_path, source_key.split(".")[0] + "-BeforeErrMap.jpg"),
                            error_map_resized )    
            bootstrap_tileRange_ls = []
            for tileRange_key in spl_tile_dic.keys() :
                tileRange = exam_tileRange_ls[tileRange_key]            #exam tile range (small)
                spl_tile =  spl_tile_dic[tileRange_key]
                inlier_tile = inliers [ spl_tile]
                inlier_rate = inlier_tile.sum() / len(inlier_tile)                          
                crop_target0 = target0[ tileRange[0]:tileRange[2],   #i: i+crop_height
                                       tileRange[1]:tileRange[3]]   #j: j + crop_width                                                
                crop_inital_diff = inital_diff[ tileRange[0]:tileRange[2],   #i: i+crop_height
                                               tileRange[1]:tileRange[3]]   #j: j + crop_width    
                crop_binary_target = binary_target[ tileRange[0]:tileRange[2],   #i: i+crop_height
                                       tileRange[1]:tileRange[3]]   #j: j + crop_width    
                crop_error = crop_inital_diff.sum()/crop_binary_target.sum()* 100 
                if ( crop_target0.mean() > target0_mean/4 and  crop_error> 1.2 and  inlier_rate < 0.4 and
                      crop_inital_diff.sum() >  ( paras.tile_shape[0] *paras.tile_shape[1]/64 ) ):
#                if ( len(inlier_tile) > paras.min_samples and inlier_rate < 0.3 and crop_error> 0.45):
                    bootstrap_tileRange_ls.append(tileRange)                                    
            print ("bootstrap_tileRange_ls=",len(bootstrap_tileRange_ls))
            
            
            diff_label_final = mpfcts. merge_diff_mask ( bootstrap_tileRange_ls, inital_diff,paras)
            
            if save_vis == True:                         
                vis_diff =  visfcts.differenceVis (inital_diff ,dst, inliers, bootstrap_tileRange_ls, diff_label_final )                        
                print (" Before : error:",error)      
                vis_diff_resized = resize(vis_diff, (vis_diff.shape[0]  // 2 , vis_diff.shape[1] // 2) ,
                                                        mode = "constant")
    
                io.imsave(os.path.join(write_path, source_key.split(".")[0] + "-BeforeErr"+ '%.1f'%error+"%_diffVis.jpg"),
                            vis_diff_resized )                   
                                                       
        if diff_label_final.max() > 0 and bootstrap == True:            
            for diff_label_obj in measure.regionprops(diff_label_final): 
                mismatch_id = diff_label_obj.label
                tileRange = diff_label_obj.bbox
                ck_tileRange=  [ max( 0 , tileRange[0] - paras.ck_shift ), 
                                 max( 0 , tileRange[1] - paras.ck_shift ),
                                 min( int(paras.target_shape[0] ) -1, tileRange[2] + paras.ck_shift) , 
                                 min( int(paras.target_shape[1] ) -1, tileRange[3] + paras.ck_shift) ]         # extract the labels of subpicious window from previous merged results
                ck_tileRange_shape = ( ck_tileRange[2] - ck_tileRange[0], ck_tileRange[3] - ck_tileRange[1] )
                
                target_tile =  target0[ ck_tileRange[0]:ck_tileRange[2],   #i: i+crop_height
                                        ck_tileRange[1]:ck_tileRange[3]]   #j: j + crop_width     # uint16                          
                source_tile =  source[ ck_tileRange[0]:ck_tileRange[2],   #i: i+crop_height
                                         ck_tileRange[1]:ck_tileRange[3]]   #j: j + crop_width     # uint16                
                fill_mask_tile = diff_label_final[ ck_tileRange[0]:ck_tileRange[2],   #i: i+crop_height
                                                   ck_tileRange[1]:ck_tileRange[3]]   #j: j + crop_width     # uint16
                fill_mask_tile = (fill_mask_tile==mismatch_id)   # extrac the binmask tile
                                
                if s_i == 0:   # Only get models from target0 source 0 
                    if reuse_kp == False:
                        model_mini = mini_register(target_tile,source_tile,paras)    # extract the model inverse map from CHN0        
                    
                    else:
                        kp0_tile = select_keypointsInMask(keypoints0, (diff_label_final==mismatch_id))
                        kp1_tile = select_keypointsInMask(keypoints1, (diff_label_final==mismatch_id))                   
                                        
                        model_mini = mini_register(target_tile,source_tile,paras , 
                                                   keypoints0[kp0_tile,:],descriptors0[kp0_tile,:],
                                                   keypoints1[kp1_tile,:],descriptors1[kp1_tile,:]  )    # extract the model inverse map from CHN0    
                    model_mini_dic[mismatch_id] = model_mini     # save the bootstrapped transform into dict
                    
                if model_mini_dic[mismatch_id]  is not None:  # only update when the model has been found                   
                    ## clear the old registered result       
                    source_warped[ ck_tileRange[0]:ck_tileRange[2],       
                                   ck_tileRange[1]:ck_tileRange[3]] = source_warped[ ck_tileRange[0]:ck_tileRange[2],       
                                                                                     ck_tileRange[1]:ck_tileRange[3]] *(1-fill_mask_tile)
                    # wrap the whole image    
                    source_warped_tile = warp( source_tile, 
                                               inverse_map = model_mini_dic[mismatch_id].inverse, 
                                               output_shape = ck_tileRange_shape)   
                    ## fill with the new one
                    source_warped[ ck_tileRange[0]:ck_tileRange[2],       
                                   ck_tileRange[1]:ck_tileRange[3]] += source_warped_tile*fill_mask_tile
            
        print ( "source_warped.type= ", source_warped.dtype)
        source_warped = img_as_uint(source_warped).astype( target0.dtype)                  
        t_ransac = time.time()

        ### save source
        if output_type is "8bit":
            tiff.imsave(os.path.join(write_path, source_key),
                        img_as_ubyte(source_warped), bigtiff= (paras.demo == False))  
        else:  # output_type is "16bit":
            print("\tsaving image as 16bit")
            tiff.imsave(os.path.join(write_path, source_key),
                         img_as_uint(source_warped), bigtiff= (paras.demo == False))  
                 
        if s_i == 0 and save_vis == True:            
            t_warp0 = time.time()
            print("[Timer] Image Warping for 1 channel ", source_key, " used time (h) =",
                  str((t_warp0 - t_ransac) / 3600))
            
            ########## save vis ############
            print("###########save vis")     
            vis, binary_diff,__,error,__= visfcts.eval_draw_diff (img_as_ubyte(target0),                                                            
                                                        img_as_ubyte(source_warped))              
                        
            print (" After : error:",error)                    
            vis_resized = resize(vis, (vis.shape[0] // 2, vis.shape[1] // 2), mode ='constant')  
            io.imsave(os.path.join(write_path, source_key.split(".")[0] + "_registeredVis.jpg"),
                         vis_resized)
            if bootstrap == False:
                vis_diff =  visfcts.differenceVis (binary_diff ,dst, inliers,
                                           tileRange_ls,diff_label_final)
            else:                
                vis_diff =  visfcts.differenceVis (binary_diff ,dst, inliers,
                                           bootstrap_tileRange_ls,diff_label_final)
                
            vis_diff_resized = resize(vis_diff, (vis.shape[0]  // 2 , vis.shape[1] // 2) ,
                                                    mode = "constant")
            io.imsave(os.path.join(write_path, source_key.split(".")[0] + "-Err"+ '%.1f'%error+"%_diffVis.jpg"),
                        vis_diff_resized )
        
    t_warp = time.time()
#    print("sources_warped.shape= ", source_warped.shape)  
    print("[Timer] Image Warping for all channels used time (h) =",
          str((t_warp - t_ransac) / 3600))
        

#%%
    return keypoints1, descriptors1


def str2bool(str_input):
    bool_result = True if str_input.lower() in ["t", 'true', '1', "yes", 'y'] else False
    return bool_result

def main():
#%%
    tic = time.time()

    ############  

    # Parameters
    print("Reading Parameteres:========")
    paras = Paras()
    paras.set_n_keypoints(args.nKeypoint)
    paras.set_max_trials(args.maxtrials)

    multiprocess = False if args.multiprocess.lower() in ["f", "0", "false"] else args.multiprocess
    paras.multiprocess(multiprocess)
    paras.keypoint_dir = args.keypoint_dir
    
    if "," in args.tiling:
        set_tile_shape = [int(s) for s in re.findall(r'\d+', args.tiling)]
        paras.set_tile_shape(set_tile_shape)
    elif args.tiling == []:
        paras.set_tile_shape([])  # no tiling, cautious might be extremely slow!
    # else is [defalut 400,600]    
    write_path = args.output_dir
    if os.path.exists(write_path) is False:
        os.mkdir(write_path)        

    assert args.outputType in ["16bit", "8bit"]

    Set_name = os.listdir(args.input_dir)[1].split("_")[0] + "_"
    Set_name = Set_name if "S" in Set_name else ""
    # the round that all other rounds are going to registered to !
    target_round = args.targetRound #"R2"

    if str2bool(args.demo) is False:
        print("Run all channels")
        # get all the channel and round id
        paras.demo = False
        channels_range = []
        source_round_ls = []
        for fileName in sorted(os.listdir(args.input_dir)):
            if "tif" in fileName and "C" in fileName:
                channel_id = fileName.split("C")[1].split(".")[0]
                if channel_id not in channels_range:
                    channels_range.append(channel_id)
                round_id = fileName.split("C")[0]
                if "_" in round_id:
                    round_id = round_id.split("_")[1]
                if round_id not in source_round_ls and round_id != target_round:
                    source_round_ls.append(round_id)
        print("channels_range=", channels_range)
        print("source_round_ls=", source_round_ls)
        
    else:  # only for testing or tunning the paras
        channels_range = [1]
        print("Run only C1 channel for all rounds")
        paras.demo = True

        source_round_ls = []
        for fileName in sorted(os.listdir(args.input_dir))[:1]:
            if "tif" in fileName and "C" in fileName:
                channel_id = fileName.split("C")[1].split(".")[0]
                if channel_id not in channels_range:
                    channels_range.append(channel_id)
                round_id = fileName.split("C")[0]
                if "_" in round_id:
                    round_id = round_id.split("_")[1]
                if round_id not in source_round_ls and round_id != target_round:
                    source_round_ls.append(round_id)
        print("args.demo :", args.demo, "\n Run for Channel ", channels_range, "\t Rounds: ", source_round_ls)

    ''' Run for images '''
    # target (reference image)
    targets = {}  # full filenames of all the images in target rounds

    for CHN in channels_range:
        target_fileName = Set_name + target_round + "C" + str(CHN) + ".tif"
        print("Read target image ", target_fileName)
        targets[target_fileName] = os.path.join(args.input_dir, target_fileName)
        shutil.copy (targets[target_fileName] , os.path.join(args.output_dir, target_fileName))
        
    # source(image to be registered)
    for sr_i, source_round in enumerate(source_round_ls):
        sources = {}  # full filenames of all the images in target rounds
        print("*" * 10 + " " + source_round + "\n")

        for CHN in channels_range:        
            source_fileName = Set_name + source_round + "C" + str(CHN) + ".tif"
            source_fileDir  = os. path.join(args.input_dir , source_fileName)   
            print (" source_fileDir = " , source_fileDir)
            if os.path.isfile (source_fileDir) == True:                                     # allow not continues channel iD               
                print("Read source image  ",source_fileName)
                sources[source_fileName] =  source_fileDir

        # Run
        if not os.path.exists(write_path):
            os.makedirs(write_path)

        save_target = True if sr_i == 0 else False  # only save target files in the last round
        
#%%
        if sr_i == 0:  # only need keypoint extraction for target for once
            keypoints1, descriptors1 = registrationORB_tiled(targets, sources, paras,                                                             
                                                            write_path=write_path,
                                                            output_type=args.outputType,
                                                            input_type=args.inputType,
                                                            save_target=save_target,
                                                            imadjust= str2bool(args.imadjust) 
                                                            )            
        else:
            _, _ = registrationORB_tiled(targets, sources, paras,
                                        write_path=write_path,
                                        output_type=args.outputType,
                                        input_type=args.inputType,
                                        save_target=save_target,
                                        imadjust=str2bool(args.imadjust),
                                        keypoints1=keypoints1,
                                        descriptors1=descriptors1)

        print("\nRegistrationORB function for round", source_round, " finished!\n====================\n")

        
    print("\nRegistrationORB function finished!\n====================\n")
    print("Result in ", write_path)

    toc = time.time()
    print("total time is (h) =", str((toc - tic) / 3600))


if __name__ == '__main__':

    start = time.time()
    main()
    print('*' * 50)
    print('*' * 50)
    print('Registeration pipeline finished successfully in {} seconds.'.format( time.time() - start))


