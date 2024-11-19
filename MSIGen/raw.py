# Agilent, Thermo data access
from multiplierz.mzAPI import mzFile

from MSIGen.msigen import MSIGen_base

from tqdm import tqdm
import numpy as np
# from scipy.interpolate import interpn#, NearestNDInterpolator

class MSIGen_raw(MSIGen_base):
    def load_files(self, *args, **kwargs):
        if not self.is_MS2 and not self.is_mobility:
            self.ms1_no_mob(*args, **kwargs)
        elif self.is_MS2 and not self.is_mobility:
            self.ms2_no_mob(*args, **kwargs)
        else:
            raise NotImplementedError('Mobility data not yet supported for .raw files.')
        
    # ==================================
    # General functions
    # ==================================
    def get_basic_instrument_metadata(self, data, metadata = {}):
        
        metadata_vars = ['filter_list']
        metadata = self.get_attr_values(metadata, data, metadata_vars)

        metadata_vars = ['CreationDate']
        source = data.source
        metadata = self.get_attr_values(metadata, source, metadata_vars)

        metadata_vars = ['Name','Model','HardwareVersion','SoftwareVersion','SerialNumber','IsTsqQuantumFile']
        inst_data = source.GetInstrumentData()
        metadata = self.get_attr_values(metadata, inst_data, metadata_vars)

        # Other parameters
        instrumental_values = []
        for i in data.scan_range():
            instrumental_values.append(i)
        #input into dict
        metadata['instrumental_values']=instrumental_values

        return metadata

    # ==================================
    # MS1 - No Mobility
    # ==================================
    def get_scan_without_zeros(self, data, scannum, centroid = False):
        # Faster implementation of multiplierz scan method for .raw files    
        scan_stats = data.source.GetScanStatsForScanNumber(scannum)
        # Does IsCentroidScan indicate that profile data is not available?
        if centroid or scan_stats.IsCentroidScan:
            
            stream = data.source.GetCentroidStream(scannum, False)
            if stream.Masses is not None and stream.Intensities is not None:
                return np.array(stream.Masses), np.array(stream.Intensities)
            else:
                # Fall back on "profile" mode, which seems to usually turn
                # out centroid data for some reason.  The format is confused.
                scan = data.source.GetSegmentedScanFromScanNumber(scannum, scan_stats) 
                return np.array(scan.Positions), np.array(scan.Intensities)
        
        else: # Profile-only scan.
            scan = data.source.GetSegmentedScanFromScanNumber(scannum, scan_stats)
            return np.array(scan.Positions), np.array(scan.Intensities)


    def ms1_no_mob(self, metadata={}, in_jupyter = None, testing = None, gui=None, pixels_per_line = None, tkinter_widgets = None, **kwargs):
        '''Takes Thermo .raw files, mass list, and metadata and extracts MS image array.'''
        # unpack variables
        for i in [("in_jupyter", in_jupyter), ("testing", testing), ("gui", gui), ("pixels_per_line", pixels_per_line), ("tkinter_widgets", tkinter_widgets)]:
            if i[1] is not None:
                setattr(self, i[0], i[1])

        # monitor progress on gui
        self.progressbar_start_preprocessing()

        # unpack variables
        MS1_list, _, MS1_polarity_list, _, _, _, _, mass_list_idxs = self.mass_list
        lb, _, _, _, _, _, _ = self.lower_lims
        ub, _, _, _, _, _, _ = self.upper_lims

        self.progressbar_start_extraction()

        pixels = []
        rts = []

        for i, file_dir in tqdm(enumerate(self.line_list), total = len(self.line_list), desc='Progress through lines', disable = self.testing or self.gui):
            
            # Get relevant data if .raw data.      
            data = mzFile(file_dir)

            headers = np.array(data.xic())

            assert len(headers)>0, 'Data from file {} is corrupt, not present, or not loading properly'.format(file_dir)
            assert headers.shape[1] == 2, 'Data from file {} is corrupt, not present, or not loading properly'.format(file_dir)

            Acq_times = np.round(headers[:,0], 4)
            num_spe = len(Acq_times)

            line_pixels = np.zeros((num_spe, MS1_list.shape[0]+1))

            # Get masses for each scan
            for j in tqdm(range(num_spe), desc = 'Progress through line {}'.format(i+1), disable = True):
                # Update line dependent gui variables            
                self.progressbar_update_progress(num_spe, i, j)

                # remove zeros from the arrays for faster slicing
                mz, intensity_points = self.get_scan_without_zeros(data, j+1, False)
                intensity_points_mask = np.where(intensity_points)
                intensity_points = np.append(intensity_points[intensity_points_mask[0]],0)
                mz = mz[intensity_points_mask[0]]            

                # get TIC
                line_pixels[j-1,0] = np.sum(intensity_points)

                if self.numba_present:
                    idxs_to_sum = self.vectorized_sorted_slice_njit(mz, lb, ub)
                    pixel = self.assign_values_to_pixel_njit(intensity_points, idxs_to_sum)
                    line_pixels[j-1,1:] = pixel
                else:
                    idxs_to_sum = self.vectorized_sorted_slice(mz, lb, ub) # Slower
                    line_pixels[j-1,1:] = np.sum(np.take(intensity_points, idxs_to_sum), axis = 1)
                # can potentially improve speed by slicing multiple pixels at a time by reshaping to a flat array and using np.take.

            data.close()
        
            pixels.append(line_pixels)
            rts.append(Acq_times)
        
        # Save average start and end retention times
        metadata['average_start_time'] = np.mean([i[0] for i in rts])
        metadata['average_end_time'] = np.mean([i[-1] for i in rts])

        self.rts = rts
        # align number and time of pixels
        pixels_aligned = self.ms1_interp(pixels, mass_list = MS1_list)

        return metadata, pixels_aligned


    # ==================================
    # MS2 - No Mobility
    # ==================================

    def ms2_no_mob(self, metadata = {}, normalize_img_sizes = None, in_jupyter = None, testing = None, gui=None, pixels_per_line = None, tkinter_widgets = None, **kwargs):
        # unpack variables
        for i in [("normalize_img_sizes", normalize_img_sizes), ("in_jupyter", in_jupyter), ("testing", testing), ("gui", gui), ("pixels_per_line", pixels_per_line), ("tkinter_widgets", tkinter_widgets)]:
            if i[1] is not None:
                setattr(self, i[0], i[1])
        
        # monitor progress on gui
        self.progressbar_start_preprocessing()
        if self.in_jupyter and not self.gui:
            print("Preprocessing data...")
        
        MS1_list, _, MS1_polarity_list, prec_list, frag_list, _, MS2_polarity_list, mass_list_idxs = self.mass_lists
        
        acq_times, all_filters_list = self.check_dim(ShowNumLineSpe = in_jupyter)
        metadata['average_start_time'] = np.mean([i[0] for i in acq_times])
        metadata['average_end_time'] = np.mean([i[-1] for i in acq_times])
        
        # for MSMS, extracts info from filters
        filters_info, polar_loc, types_loc, filter_inverse = self.get_filters_info(all_filters_list)
        # Determines correspondance of MZs to filters
        PeakCountsPerFilter, mzsPerFilter, mzsPerFilter_lb, mzsPerFilter_ub, mzIndicesPerFilter = self.get_PeakCountsPerFilter(filters_info)
        # finds the number of scans that use a specific filter
        scans_per_filter = self.get_ScansPerFilter(filters_info, polar_loc, types_loc, all_filters_list = all_filters_list)
        # Groups filters into groups containing the same mzs/transitions
        consolidated_filter_list, mzs_per_filter_grp, mzs_per_filter_grp_lb, mzs_per_filter_grp_ub, \
            mz_idxs_per_filter_grp, scans_per_filter_grp, peak_counts_per_filter_grp, consolidated_idx_list \
            = self.consolidate_filter_list(filters_info, mzsPerFilter, scans_per_filter, mzsPerFilter_lb, mzsPerFilter_ub, mzIndicesPerFilter)
        num_filter_groups = len(consolidated_filter_list)

        # get an array that gives the scan group number from the index of any scan (1d index)
        grp_from_scan_idx = np.empty((len(filters_info[0])), dtype = int)
        for idx, i in enumerate(consolidated_idx_list):
            for j in i:
                grp_from_scan_idx[j]=idx
        grp_from_scan_idx = grp_from_scan_idx[filter_inverse]

        # monitor progress on gui
        self.progressbar_start_extraction()

        all_TimeStamps = []
        pixels_metas = []
        
        # holds index of current scan
        scan_idx = 0

        for i, Name in tqdm(enumerate(self.line_list), desc = 'Progress through lines', total = len(self.line_list), disable = (self.testing or self.gui)):
            # accumulators for all fitlers,for line before interpolation, interpolation: intensity, scan/acq_time
            TimeStamps = [ np.zeros((scans_per_filter_grp[i][_])) for _ in range(num_filter_groups) ] # spectra for each filter
            # counts how many times numbers have been inputted each array
            counter = np.zeros((scans_per_filter_grp[0].shape[0])).astype(int)-1 # start from -1, +=1 before handeling
            
            if Name.lower().endswith('.raw'):
                data = mzFile(Name)
                
                # # collect metadata from raw file
                # if i == 0:
                #     metadata = get_basic_instrument_metadata_raw_no_mob(RawFile, metadata)

                # The intensity values for all masses/transitions in the mass list. 0 index in each group = TIC.
                pixels_meta = [ np.zeros((scans_per_filter_grp[i][_] , peak_counts_per_filter_grp[_] + 1)) for _ in range(num_filter_groups) ]

                # counts how many times numbers have been inputted each array
                counter = np.zeros((scans_per_filter_grp[0].shape[0])).astype(int)-1 # start from -1, +=1 before handeling

                for j, TimeStamp in tqdm(enumerate(acq_times[i]), disable = True):
                    # Update gui variables
                    self.progressbar_update_progress(len(acq_times[i]), i, j)


                    # determine which group is going to be used
                    grp = grp_from_scan_idx[scan_idx]
                    counter[grp]+=1

                    # handle info
                    TimeStamps[grp][counter[grp]] = TimeStamp 

                    # get spectrum
                    mz, intensity_points = self.get_scan_without_zeros(data, j+1, False)

                    # get TIC
                    pixels_meta[grp][counter[grp], 0] = np.sum(intensity_points)

                    # skip filters with no masses in the mass list
                    if peak_counts_per_filter_grp[grp]:

                        # remove all values of zero to improve speed
                        intensity_points_mask = np.where(intensity_points)
                        mz = mz[intensity_points_mask[0]]
                        intensity_points = np.append(intensity_points[intensity_points_mask[0]],0)
                        
                        lbs,ubs = mzs_per_filter_grp_lb[grp], mzs_per_filter_grp_ub[grp] 

                        # TODO: Get this to work with the numba workflow
                        ### did not work properly with numba
                        # if self.numba_present:
                        #     idxs_to_sum = self.vectorized_sorted_slice_njit(mz, lbs, ubs)
                        #     pixel = self.assign_values_to_pixel_njit(intensity_points, idxs_to_sum)
                        #     pixels_meta[grp][counter[grp],1:] = pixel
                        # else:
                        idxs_to_sum = self.vectorized_sorted_slice(mz, lbs, ubs) # Slower
                        pixels_meta[grp][counter[grp],1:] = np.sum(np.take(intensity_points, idxs_to_sum), axis = 1)

                    # keep count of the 1d scan index
                    scan_idx += 1

                data.close()

            all_TimeStamps.append(TimeStamps)
            pixels_metas.append(pixels_meta)

        self.rts = acq_times
        pixels, all_TimeStamps_aligned = self.ms2_interp(pixels_metas, all_TimeStamps, acq_times, scans_per_filter_grp, mzs_per_filter_grp)

        # Order the pixels in the way the mass list csv/excel file was ordered
        pixels = self.reorder_pixels(pixels, consolidated_filter_list, mz_idxs_per_filter_grp, mass_list_idxs, filters_info)    
        if normalize_img_sizes:
            pixels = self.pixels_list_to_array(pixels, all_TimeStamps_aligned)

        return metadata, pixels 

    def reorder_pixels(self, pixels, filters_grp_info, mz_idxs_per_filter, mass_list_idxs, filters_info = None):
        # get the scan type/level 
        iterator = [] 
        for filter_grp in filters_grp_info:
            iterator.append(filters_info[2][np.where(filter_grp[0]==filters_info[0])])

        #put pixels into a list. If the window is MS1, its first mass will be assumed to be TIC.
        pixels_reordered = [np.zeros((1,1))]*(len(mass_list_idxs[0])+len(mass_list_idxs[1])+1)
        for i, acq_type in enumerate(iterator):
            if acq_type in ['MS1', 1, '1', 'Full ms']:
                pixels_reordered[0] = pixels[i][:,:,0]
                for j in range(pixels[i].shape[-1]-1):
                    pixels_reordered[mass_list_idxs[0][mz_idxs_per_filter[i][j]]+1]=pixels[i][:,:,j+1]
            else:
                for j in range(pixels[i].shape[-1]-1):
                    pixels_reordered[mass_list_idxs[1][mz_idxs_per_filter[i][j]]+1]=pixels[i][:,:,j+1]

        return pixels_reordered


    def check_dim(self, ShowNumLineSpe=False):
        """Gets the times and other information about each scan to decide 
        what peaks can be obtained from each scan."""

        acq_times = []
        filter_list = []

        # Get Start times, end times, number of spectra per line, and list of unique filters.
        for file_dir in self.line_list:
            # Get relevant data if .raw data.      
            data = mzFile(file_dir)

            if self.is_MS2:
                rts_and_filters = np.array(data.filters())
                # Check if there is a rt and a filter in the filters data
                assert len(rts_and_filters)>0, 'Data from file {} is corrupt, not present, or not loading properly'.format(file_dir)
                assert rts_and_filters.shape[1] == 2, 'Data from file {} is corrupt, not present, or not loading properly'.format(file_dir)
                acq_times.append(rts_and_filters[:,0].astype(float))
                filter_list.append(rts_and_filters[:,1])
            data.close()
    
        num_spe_per_line = [len(i) for i in acq_times]
        # show results
        if ShowNumLineSpe:
            print('\nline scan spectra summary\n# of lines is: {}\nmean # of spectra is: {}\nmin # of spectra is: {}\nmean start time is {}\nmean end time is: {}'.format(
                len(num_spe_per_line), int(np.mean(num_spe_per_line)), int(np.min(num_spe_per_line)),np.mean([i[0] for i in acq_times]),np.mean([i[-1] for i in acq_times])))

        return acq_times, filter_list

    def get_filters_info(self, filter_list):
        '''
        Gets information about all filters present in the experiment.
        output: [filter_list, polarities, MS-levels, precursors, mz_ranges], index of polarity and ms level in filter, and an inverse mask for the filters
        '''
        acq_polars = [] # + or -
        acq_types = [] # ms or ms2
        mz_ranges = [] # mass window
        precursors = [] # ms -> 0, ms2 -> pre + frag

        potential_polars = ['+','-']
        polar_loc = None # where in the filter polarity is
        potential_types = ['Full', 'sim', 'SIM', 'Sim', 'ms', 'ms2']
        types_loc = [] # where to find acq_type in filter
                    
        filter_list, filter_inverse = np.unique([i.split('[')[0]+'[100.0, 950.0]' if 'ms ' in i else i for i in self.flatten_list(filter_list)], return_inverse=True)   # remove extra ms1 filters
        # Get polarities
        for Filter in filter_list:
            string = Filter.split(' ')
            # determine location of polarity info in filter
            if polar_loc == None:
                for i in range(len(string)):
                    if string[i] in potential_polars:
                        polar_loc = i
            # get polarity data
            acq_polar = string[polar_loc]
            if acq_polar == '+':
                acq_polars.append(1.)
            elif acq_polar == '-':
                acq_polars.append(-1.)
            else:
                acq_polars.append(0.)

            # determine location of acq types
            if types_loc == []:
                for i in range(len(string)):
                    if string[i] in potential_types:
                        types_loc.append(i)
            # get acq type data
            acq_type = string[types_loc[0]] + ' ' + string[types_loc[1]]
            acq_types.append(acq_type)

            # get mass ranges
            mz_start = float(Filter.split('[')[-1].split(',')[0].split('-')[0].split(' ')[0])
            mz_end = float(Filter.split(' ')[-1].split('-')[-1].split(',')[-1].split(']')[0])
            mz_ranges.append([mz_start, mz_end])

            # get precursor if ms2 scan, else 0
            if 'ms2' in acq_type:
                precursor = float(Filter.split('@')[0].split(' ')[-1])
            else:
                precursor = 0.0
            precursors.append(precursor)
            
        acq_types, acq_polars, precursors, mz_ranges = np.array(acq_types), np.array(acq_polars), np.array(precursors), np.array(mz_ranges)

        return [filter_list, acq_polars, acq_types, precursors, mz_ranges], polar_loc, types_loc, filter_inverse

    def get_ScansPerFilter(self, filters_info, polar_loc, types_loc, all_filters_list, display_tqdm = False):
        '''
        Determines the number of scans per line that have each filter.
        '''
        # unpack filters_info
        filter_list, acq_polars, acq_types, precursors, mz_ranges = filters_info

        # accumulator
        scans_per_filter = np.empty(([0, filter_list.shape[0]])).astype(int)

        for i, Name in tqdm(enumerate(self.line_list), disable = not display_tqdm):
            # counter for a line
            Dims = np.zeros((filter_list.shape[0])).astype(int)

            if Name.lower().endswith('.raw'):
                # Get each filter
                for j in range(len(all_filters_list[i])):
                    Filter = all_filters_list[i][j]

                    # Get the filter index of the scan
                    idx = self.get_filter_idx(Filter,polar_loc,types_loc,acq_types,acq_polars,mz_ranges,precursors,filter_list)

                    # count on 
                    Dims[idx] += 1

                # count on
                scans_per_filter = np.append(scans_per_filter, Dims.reshape((1, acq_polars.shape[0])), axis=0)

        return scans_per_filter

    def get_filter_idx(self, Filter, polar_loc, types_loc, acq_types, acq_polars, mz_ranges, precursors, filter_list):
        '''Gets the index of the current Thermo filter'''
        acq_polar = Filter.split(' ')[polar_loc]

        if acq_polar == '+':
            polarity_numeric = 1.0
        elif acq_polar == '-':
            polarity_numeric = -1.0

        acq_type = Filter.split(' ')[types_loc[0]] + ' ' + Filter.split(' ')[types_loc[1]]                

        if acq_type == 'Full ms':   # since filter name varies for ms, we just hard code this situation. 
            precursor = 0.0
            mz_range = [100.0, 950.0]
            mz_range_judge = np.array(mz_range).reshape(1, 2) == mz_ranges.astype(float)    

        # to match look-up table: acq_types, acq_polars, precursors
        if acq_type == 'Full ms':
            idx = (polarity_numeric == acq_polars)&(acq_type == acq_types)&(mz_range_judge[:,0])&(mz_range_judge[:,1])
            idx = np.where(idx)[0]
        if acq_type == 'Full ms2': 
            idx = np.where(Filter == filter_list)
        return idx
