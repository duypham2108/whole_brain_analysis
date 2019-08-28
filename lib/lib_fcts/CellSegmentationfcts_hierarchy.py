# -*- coding: utf-8 -*-
"""
Created on Thu Jul 13 14:59:38 2017

@author: xli63
"""

import os

#os.chdir(r'D:\research in lab\NIHIntern(new)\RebeccaCode')  # set current working directory
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import cv2
import numpy as np
import skimage
from skimage import util,segmentation,exposure,filters, morphology,measure,feature,io
from scipy import ndimage,stats,cluster,misc,spatial
from sklearn.cluster import KMeans
from sklearn.neighbors  import NearestNeighbors

import numpy as np
import cv2
import heapq
import matplotlib.image as mpimg
import matplotlib.pyplot as plt
from math import sqrt

import sys
#sys.path.insert(0, os.getcwd()+'/lib_fcts')
#import CellSegmentationfcts as myfcts                                          # my functions
#from Dataset_read_TBI_BFcorrected import Dataset_read_TBI                                  # read file proterty files
#ds = Dataset_read_TBI()                                                            # define a class to read the input channels image(image name and paramaters)



def LoG_seed_detection (IMG, blob_LoG_Para):
    blobRadius_min = blob_LoG_Para[0];
    blobRadius_max = blob_LoG_Para[1];
    num_sigma      = blob_LoG_Para[2];
    blob_thres     = blob_LoG_Para[3];
    overlap        = blob_LoG_Para[4];
    blob_radius_range_pixel = np.array([blobRadius_min, blobRadius_max])
    blob_radius_range = blob_radius_range_pixel /1.414                                    #  radius approximate root 2 * sigma 
    #plt.figure(),plt.imshow(image_masked,cmap='gray')
    blobs_LoG  = feature.blob_log (
                        IMG, min_sigma = blob_radius_range[0], max_sigma = blob_radius_range[1] , 
                        num_sigma = num_sigma,                                           # number of sigma consider between the range
                        threshold = blob_thres , overlap= overlap
                       )     
#    print('LoG_seed_detection done  LoG_Paras are: ', blob_LoG_Para)
    return blobs_LoG

def GenerateSeeds_marker(IMG,blobs,diskR = 3):   # start with 1.2...   
    seed_centroidImg = np.zeros_like(IMG)
    for i,(x,y) in enumerate( zip( np.uint(blobs[:,0]), np.uint(blobs[:,1]) ) ):         #blobs read from seed detection result (blobs_log) or seed table
        seed_centroidImg[x,y] = (i+1)                    # disks of seeds are label as their id (1,2,3....)
    seeds_marker = morphology.dilation (seed_centroidImg,morphology.disk(diskR))         # sure forground (marked) is from blobs with same radius
#    blobs = []
#    for obj in measure.regionprops(Label_IMG)   :         #blobs read from seed detection result (blobs_log) or seed table
#        x = np.uint(obj.centroid[0])
#        y = np.uint(obj.centroid[1])
#        blobs.append([x,y]) 
#        seed_centroidImg[x,y] = obj.label                   # disks of seeds are label as their id (1,2,3....)
#    seeds_marker = morphology.dilation (seed_centroidImg,morphology.disk(diskR))         # sure forground (marked) is from blobs with same radius
#        
    return seeds_marker

def binMaskCorrection(img, thres_value):
    bin_mask = img > thres_value                             # generate binary mask from original image
    bin_mask = morphology.binary_dilation (bin_mask,morphology.disk(3))                        
#    bin_mask = morphology.binary_opening (bin_mask,morphology.disk(3))                 # remove white noise for
    bin_mask = morphology.binary_closing(bin_mask,morphology.disk(3))                   # remove dark noise for
    bin_mask = ndimage.binary_fill_holes(bin_mask, morphology.disk(5))                  # filling holes
    bin_mask = morphology.binary_closing (bin_mask,morphology.disk(3))                        
    return bin_mask

def borderCorrection( bin_mask_border, maskCorrectR):                 # need shape correction 
    bin_mask_border = morphology.binary_dilation  (bin_mask_border,morphology.disk(5))       # # remove dark noise for

    bin_mask_border = morphology.binary_closing  (bin_mask_border,morphology.disk(maskCorrectR))       # # remove dark noise for
    bin_mask_border = ndimage.binary_fill_holes  (bin_mask_border,morphology.disk(maskCorrectR))       # filling holes
#                bin_mask_border = morphology.binary_closing  (bin_mask_border,morphology.disk(maskCorrectR))       # # remove dark noise for
    bin_mask_border = morphology.binary_opening  (bin_mask_border,morphology.disk(5))                # # remove white noise for
    
    bin_mask_border = morphology.binary_erosion  (bin_mask_border,morphology.disk(5))       
    
    return bin_mask_border


def watershedSegmentation( img, blobs, maskCorrectR = 0, maskDilateR = 0, LoG_Para = [],Bootstrap = False  , offset = 0.15):
    # blobs could either from outside or generated from loG in this function
    # the more offset, the more small element to be captured
    
#    plt.figure()
#    plt.imshow(img,cmap ='gray')
    #
    otsu_thres = filters.threshold_otsu(img)
    bin_mask_level1 = binMaskCorrection(img, (1 -  offset) * otsu_thres)
    
    if maskDilateR!=0:     # enlarge the border for small components
        bin_mask_level1 = morphology.binary_dilation  (bin_mask_level1,morphology.disk(maskDilateR))     
    if maskCorrectR!=0:   # fill in holes
        bin_mask_level1 = borderCorrection( bin_mask_level1, maskCorrectR)    
        
    ###################
    if blobs != []:  # read blob from outside ,implememnt global watershed      
        seeds_marker = GenerateSeeds_marker (img, blobs)    
        D             = ndimage.distance_transform_edt(bin_mask_level1)                                         # generate distant map, centrois locates in peaks
        D_exactShape  = ndimage.distance_transform_edt(img>otsu_thres)          
        D = D + 5 * D_exactShape                                                                  #!!!!!!!!!! correct the border shape
        #    D = morphology.erosion(D,morphology.disk(3))
        labels = morphology.watershed(-D, seeds_marker,  mask = bin_mask_level1)                   # labeled components, background = 0, other= ID, with eact shape of blobs

        #Generate sure foreground
        PropertyTable = measure.regionprops(labels, intensity_image = img)
        updated_blobs = []
        
    else:#  blobs will generated from loG,implement hierarchy watershed and LoG                , create blob    
        label_level1 = skimage.morphology.label(bin_mask_level1, neighbors=None, background=None, return_num=False, connectivity=None)  # Label connected regions of an integer array.
        label_level2 = label_level1.copy()
        
        label_level2_ID = label_level1.max()                                                # label of label_level2  should start with label_level1.max() 
    #    plt.figure(),plt.imshow(label_level1) 
    
        #### within each crops
        connected_area = int(3.14 *  ( (LoG_Para[0] *2.5)/2 ) **2 )
        smallest_area  = int(3.14 *  ( (LoG_Para[0] /2  )/2 ) **2 )
    
        PropertyTable_1st = measure.regionprops(label_level1,intensity_image=img)                  # storage the properties e.g ID,area  of each componentes (labelled regions)
        for connected_obj in PropertyTable_1st :
            if connected_obj.area < smallest_area : 
                # clean the labels
                label_level2[connected_obj.coords[:,0],connected_obj.coords[:,1]]  = 0               
                
            elif connected_obj.area > connected_area :   # size = 600
                
    #            connected_obj = PropertyTable_1st[209]
                connected_Crop =    connected_obj.intensity_image           # size = 600
                
                # clean the labels
                label_level2[connected_obj.coords[:,0],connected_obj.coords[:,1]]  = 0        
                
                # enlarger the window for crop
                enlarge_width = 5
                connected_Crop_enlarged = np.zeros( (connected_Crop.shape[0] + 2* enlarge_width , 
                                                     connected_Crop.shape[1] + 2* enlarge_width )  )
                connected_Crop_enlarged[enlarge_width : enlarge_width + connected_Crop.shape[0],
                                        enlarge_width : enlarge_width + connected_Crop.shape[1]] = connected_Crop
                       
                # correct he blog
                
                otsu_thres_Crop = filters.threshold_otsu(connected_Crop_enlarged)                
                bin_mask_border       = binMaskCorrection(connected_Crop_enlarged,  (1 -  offset) * otsu_thres) 
                bin_mask_exactShape   = connected_Crop_enlarged > otsu_thres_Crop        
                bin_mask_shrinked     = connected_Crop_enlarged > (1 + 0.15) * otsu_thres_Crop    
        
                D_exactShape = ndimage.distance_transform_edt(bin_mask_exactShape)                                             # generate distant map, centrois locates in peaks
                D_shrinked  = ndimage.distance_transform_edt(bin_mask_shrinked)  
                
                D = D_shrinked + 5 * D_exactShape
                
                #Generate sure foreground
    #            img_Intensed = connected_Crop_enlarged + filters.prewitt(connected_Crop_enlarged, mask= bin_mask_exactShape)      # add laplace fileter to it more intensive
                
                Crop_blobs = LoG_seed_detection (connected_Crop_enlarged,  LoG_Para)          #   [7, 20, 35, 0.015, 0.5]  
    #            else:  #  blobs   from input
    ##                X = np.uint(blobs[:,0])     # X coordiniates of blob(N *1)
    ##                Y = np.uint(blobs[:,1])     # Y coordiniates of blob(N *1)
    #                (min_row, min_col, max_row, max_col) = connected_obj.bbox              
    #                X_bdId = np.logical_and(blobs[:,0] >= min_row, blobs[:,0] < max_row)     # X bounded IDs
    #                Y_bdId = np.logical_and(blobs[:,1] >= min_col, blobs[:,1] < max_col )     # Y bounded IDs
    #                bdID = np.logical_and (X_bdId ,Y_bdId )      
    #                                                            # fix both X and Y bounded                
    #                Crop_blobs_abs = blobs[bdID,:]    # absolute blobs's coordinate
    #                Crop_blobs_rel = Crop_blobs_abs
    #                Crop_blobs_rel[:,0] = Crop_blobs_abs[:,0] - min_row   + enlarge_width  # relative X coordinate
    #                Crop_blobs_rel[:,1] = Crop_blobs_abs[:,1] - min_col   + enlarge_width  # relative Y coordinate
    #                Crop_blobs_rel[:,2] = Crop_blobs_abs[:,2]                              # r
    #                
    #                Crop_blobs = Crop_blobs_rel           
    
                    
    
        #        # correction of Crop_blobs
        #        Crop_blobs_corrected = []
        #        for i in range(len(Crop_blobs)):
        #            Crop_blob = Crop_blobs[i,:]
        #            if (Crop_blob[0]!= 0) and (Crop_blob[1]!= 0) :                    # only the blob with x,y all ! =0 save as corrected blob
        #                Crop_blobs_corrected.append(Crop_blob)
        #                
        #        local_maxi = feature.peak_local_max(D, indices=True , min_distance = 100, footprint=np.ones((7, 7)), labels= None)
                    
                
                seeds_marker_crop = GenerateSeeds_marker (connected_Crop_enlarged, Crop_blobs)
                
                
    
                    
            #     Implement Watershed 
                labels_Crops_enlarged = morphology.watershed(-D, seeds_marker_crop,  mask = bin_mask_border)                   # labeled components, background = 0, other= ID, with eact shape of blobs
                
                labels_Crops = labels_Crops_enlarged[enlarge_width : enlarge_width + connected_Crop.shape[0],         # recover it back from enlarged image
                                                     enlarge_width : enlarge_width + connected_Crop.shape[1]]
                labels_Crops = labels_Crops * connected_obj.filled_image                                         # make sure it don't bleed ousider the level 1 crop
              
               # within the connected_crops
                
                for obj_inCrop in measure.regionprops(labels_Crops) :             # the fill the labels_crops in to whole label image
                    for i in  range (obj_inCrop.coords.shape[0]):                # for each pixel in the crops
                        label_level2[ connected_obj.bbox[0] + obj_inCrop.coords[i,0],
                                      connected_obj.bbox[1] + obj_inCrop.coords[i,1] ]  = label_level2_ID + obj_inCrop.label       # the label should start with the largetst label 
                    label_level2_ID = label_level2_ID + obj_inCrop.label         # add the current largest label         
    #         
    #     
    #         
    ##            plt.figure(),plt.imshow(label_level2)
    #    
    #    #        for obj in PropertyTable_1st :
    #    
    #    #        PropertyTable_1st = measure.regionprops(labels_Crops, intensity_image=img)                  # storage the properties e.g ID,area  of each componentes (labelled regions)
    #            f, axarr = plt.subplots(2, 2)
    #            axarr[0, 0].set_title('Connected Region Crop')
    #            axarr[0, 0].imshow(connected_Crop,cmap='gray')       
    #            axarr[0, 0].plot(Crop_blobs[:,1],Crop_blobs[:,0],'r.')
    #            
    #            axarr[1, 0].set_title('Distance Map')   
    #            axarr[1, 0].imshow(D)      
    #                                   
    #            axarr[0, 1].set_title('Mask')  
    #            axarr[0, 1].imshow(bin_mask_border)      
    #            
    #            axarr[1, 1].set_title('Labeled Image')  
    #            axarr[1, 1].imshow(labels_Crops)
    #            
    #            loca= (r'D:\research in lab\NIHIntern(new)\RebeccaCode\Datasets_and_Results\TBI\NIH_Poster\CompareRegionCrops3animals\CroppedImgs\Outputs\\')
    #            figName = 'connected_Crop_No_' + str(obj.label) + '.tif'
    #            
    #            f.savefig( loca + figName )
    #            plt.close('all')
    #    
                
            
    
        
        
    #    bin_mask_shrinked = binMaskCorrection(img, otsu_thres)
    
    #    img_Intensed = img + filters.laplace(img, ksize=10, mask=bin_mask)      # add laplace fileter to it more intensive
    
    #    border_otsuMask = segmentation.find_boundaries(bin_mask)
        
    #''' Improve the thresholding'''
    ##img_Intensed = img + filters.laplace(img, ksize=10)      # add laplace fileter to it more intensive
    #adaptive_thresh = filters.threshold_triangle(util.invert(img), nbins=528)
    #new = morphology.h_minima(img, h =1, selem= morphology.disk(1))
    #new = morphology.binary_closing (new,morphology.disk(3))                      
    #
    #plt.figure(),plt.imshow(new , cmap= 'gray')
    #
    #plt.figure(),plt.imshow(img, cmap= 'gray')
    
    
    
    
    #  _________
        
    #    D = morphology.erosion(D,morphology.disk(3))
    #    plt.figure(),plt.imshow(label_level2 )
    
        #Generate sure foreground
        
        
        # put into result
    
        
        
       
        
    #    plt.figure(),plt.imshow(labels)
    
            
    #    
    
    #    
    #    bin_mask = np.logical_or(bin_mask, (seeds_marker_1st>0) )                             # make sure the seeds marker has considered
    #    
        
        
    ##     Implement Watershed 
    #    labels_1st = morphology.watershed(-D, seeds_marker_1st, mask=bin_mask)                   # labeled components, background = 0, other= ID, with eact shape of blobs
    #    PropertyTable_1st = measure.regionprops(labels_1st,intensity_image=img)                  # storage the properties e.g ID,area  of each componentes (labelled regions)
    ##    
        
        
        labels = segmentation.relabel_sequential(label_level2 , offset=1)[0]
        
        if Bootstrap == True:  ## adjust the labels by itself   will change the number of cells!!
            Mask_2nd = np.zeros_like(bin_mask_level1)
            #1) find the missing compoments
            missingmask = np.logical_xor(bin_mask_level1,(label_level2>0))
            missingmask_label = skimage.morphology.label(missingmask)   # Label connected regions of an integer array.
            for missingComponent in measure.regionprops(missingmask_label):
                if missingComponent.area > 100:  # the missing component is big enough
                    Mask_2nd[missingmask_label == missingComponent.label] = 1       
                    
            missingmask_label =  missingmask_label * Mask_2nd
            missingmask_label =  segmentation.relabel_sequential(missingmask_label , offset = label_level2.max())[0]
            labels = labels + missingmask_label         
       
    
        seed_centroidImg = np.zeros_like(labels)
        PropertyTable = measure.regionprops(labels)          
        
        updated_blobs = []
        for obj in PropertyTable  :         #blobs read from seed detection result (blobs_log) or seed table
            x = np.uint(obj.centroid[0])
            y = np.uint(obj.centroid[1])
            r = obj.equivalent_diameter/2
            updated_blobs.append([x,y,r]) 
            seed_centroidImg[x,y] = obj.label                   # disks of seeds are label as their id (1,2,3....)
        seeds_marker = morphology.dilation (seed_centroidImg,morphology.disk(3))         # sure forground (marked) is from blobs with same radius
        
        updated_blobs = np.array(updated_blobs)        

        
    print('Use watershed generate segmentation borders done!')
    
    return seeds_marker, labels, PropertyTable,updated_blobs

