import astropy.units as u
import astropy.stats as astat
from astropy.time import Time
import astropy, astroplan
import numpy as np
import os
import SYNEX.SYNEX_Utils as SYU
from SYNEX.SYNEX_Utils import SYNEX_PATH
import gwemopt
import json
from datetime import date
import pathlib
import pickle
import matplotlib
import matplotlib.pyplot as plt
import scipy
import copy

# mpi stuff
try:
    from mpi4py import MPI
except ModuleNotFoundError:
    MPI = None





class Athena:
    """
    Class to make a Space Based Instrument using the Interferometer base class

    Parameters
    ----------
    telescope_go_params : (gwemopt compatible) dict
        See './SYNEX/gwemopt_defaults.py' all possible flags.

    telescope_config_struct : (gwemopt compatible) dict
        See './SYNEX/gwemopt_defaults.py' all possible flags.

    ExistentialFileName : Path or string
        Path and file name of file loadable by 'pickle'. Contents are a
        dictionary containing all the kwargs of a saved 'Athena' class object.
        If ExistentialFileName is specified but the file doesn't exist, then it
        will be automatically created so that the class can be loaded again later.
        Automatic save points through SYNEX routines will update this savefile

    NB: GWEMOPT uses serialized dictionaries 'go_params' and 'config_struct'.
        These are constructed with one or more 'telescope_go_params' or
        'telescope_config_struct' under key values given by the 'telescope' name.
        You might experience errors if you try passing 'telescope_go_params' or
        'telescope_config_struct' directly to GWEMOPT. You will need to pass classes
        through an interface routine like SYNEX_Utils.InitGWEMOPTParamsFromTelescopes.py
        (doesn't exist yet...) to prepare the dictionaries for use in GWEMOPT.
    """

    def __init__(self, **kwargs):
        """
        TO DO:
        ------
        --> Need to add a check when loading a source form savefile that there aren't any additional
            params in defaults that aren't in the savefile and add their defaults. This is why 'Ntiles'
            isn't being changed when you load older savefiles and add it to them.
        """
        # Set verbosity
        self.verbose=kwargs.pop("verbose") if "verbose" in kwargs else True

        # Default is not to recompute tesselation if the saved '.tess' file exists
        MUTATED=False

        # Default coverage dict is None
        telescope_source_coverage=None
        telescope_tile_struct=None
        telescope_tile_struct=None

        # Make sure to handle case where we are in cluster so we don't write too many files and exceed disk quota
        # self.use_mpi=kwargs["use_mpi"] if "use_mpi" in kwargs else False
        if MPI is not None:
            MPI_size = MPI.COMM_WORLD.Get_size()
            MPI_rank = MPI.COMM_WORLD.Get_rank()
            comm = MPI.COMM_WORLD
            use_mpi=(MPI_size > 1)
        else:
            use_mpi=False
            MPI_rank=0
        self.PermissionToWrite=not use_mpi # MPI_rank==0 # This will not write orbit file since it is memory instensive

        # Check filename paths to SYNEX
        if "NewExistentialFileName" in kwargs.keys():
            ExPath="/".join(kwargs["NewExistentialFileName"].split("/")[:-1])
            try:
                pathlib.Path(ExPath).mkdir(parents=True, exist_ok=True)
            except:
                kwargs["NewExistentialFileName"]=SYNEX_PATH+"/"+kwargs["NewExistentialFileName"].split("/SYNEX/")[-1]

        # Check if we are resurrecting a class from a save file
        if "ExistentialFileName" in kwargs.keys():
            self.ExistentialFileName=kwargs["ExistentialFileName"]
            del kwargs["ExistentialFileName"]
            ExPath="/".join(self.ExistentialFileName.split("/")[:-1])
            try:
                pathlib.Path(ExPath).mkdir(parents=True, exist_ok=True)
            except:
                self.ExistentialFileName=SYNEX_PATH+"/"+self.ExistentialFileName.split("/SYNEX/")[-1]
            if os.path.isfile(self.ExistentialFileName):
                # FUSE THIS WITH CONFIG KEY IN GO_PARAMS... Save in two files so we
                # respect gwemopt conventions? Seems overkill but 'gwemop.utils.readParamsFromFile(file)'
                # already exists and can be used for both 'config' and 'params' dictionaries.

                # Load saved dictionary
                with open(self.ExistentialFileName, 'rb') as f:
                    SavedDict = pickle.load(f)

                # Use these values as default to modify with remaining keys in '**kwargs'
                telescope_go_params = SavedDict["telescope_go_params"]
                telescope_config_struct = SavedDict["telescope_config_struct"]
                if "telescope_source_coverage" in SavedDict and SavedDict["telescope_source_coverage"]!=None:
                    telescope_source_coverage = SavedDict["telescope_source_coverage"] # None if not calculated yet
                    # Make sure we adapt the savefiles to this achitecture if we need to... (e.g. if copied across from cluster)
                    if telescope_source_coverage["source JsonFile"]!=None and "/SYNEX/" in telescope_source_coverage["source JsonFile"]: telescope_source_coverage["source JsonFile"]=SYNEX_PATH+"/"+telescope_source_coverage["source JsonFile"].split("/SYNEX/")[-1]
                    if telescope_source_coverage["source H5File"]!=None and "/SYNEX/" in telescope_source_coverage["source H5File"]: telescope_source_coverage["source H5File"]=SYNEX_PATH+"/"+telescope_source_coverage["source H5File"].split("/SYNEX/")[-1]
                    if telescope_source_coverage["source save file"]!=None and "/SYNEX/" in telescope_source_coverage["source save file"]: telescope_source_coverage["source save file"]=SYNEX_PATH+"/"+telescope_source_coverage["source save file"].split("/SYNEX/")[-1]
                    # Check for file architecture missing when copied from cluster...
                    if telescope_source_coverage["source JsonFile"]!=None and not os.path.isfile(telescope_source_coverage["source JsonFile"]):
                        # Can't find file- check for missing architecture
                        FileWithArch = SYNEX_PATH + "/inference_param_files/" + "/".join(self.ExistentialFileName.split("/Saved_Telescope_Dicts/")[-1].split("/")[:-1]) + "/" + telescope_source_coverage["source JsonFile"].split("/")[-1]
                        if os.path.isfile(FileWithArch): telescope_source_coverage["source JsonFile"]=FileWithArch
                    if telescope_source_coverage["source H5File"]!=None and not os.path.isfile(telescope_source_coverage["source H5File"]):
                        # Can't find file- check for missing architecture
                        FileWithArch = SYNEX_PATH + "/inference_data/" + "/".join(self.ExistentialFileName.split("/Saved_Telescope_Dicts/")[-1].split("/")[:-1]) + "/" + telescope_source_coverage["source H5File"].split("/")[-1]
                        if os.path.isfile(FileWithArch): telescope_source_coverage["source H5File"]=FileWithArch
                    if telescope_source_coverage["source save file"]!=None and not os.path.isfile(telescope_source_coverage["source save file"]):
                        # Can't find file- check for missing architecture
                        FileWithArch = SYNEX_PATH + "/Saved_Source_Dicts/" + "/".join(self.ExistentialFileName.split("/Saved_Telescope_Dicts/")[-1].split("/")[:-1]) + "/" + telescope_source_coverage["source save file"].split("/")[-1]
                        if os.path.isfile(FileWithArch): telescope_source_coverage["source save file"]=FileWithArch
                else:
                    telescope_source_coverage = None # None if not calculated yet
                if "telescope_tile_struct" in SavedDict:
                    telescope_tile_struct = SavedDict["telescope_tile_struct"] # None if not calculated yet
                else:
                    telescope_tile_struct = None # None if not calculated yet
                if "telescope_tile_struct" in SavedDict:
                    telescope_tile_struct = SavedDict["telescope_tile_struct"] # None if not calculated yet
                else:
                    telescope_tile_struct = None # None if not calculated yet
                self.MutatedFromTelescopeFile=SavedDict["MutatedFromTelescopeFile"] if "MutatedFromTelescopeFile" in SavedDict else None

                if "NewExistentialFileName" in kwargs:
                    # save file exists already and have a new one specified so mutate loaded source regardless
                    MUTATED=True
                elif len(kwargs.keys())>1:
                    # Check if we will modify something later (treat Tobs seperately because its an array...)
                    ValueCheck1 = [value!=telescope_go_params[key] for key,value in kwargs.items() if key in telescope_go_params and key not in ["Tobs"]]
                    ValueCheck2 = [value!=telescope_config_struct[key] for key,value in kwargs.items() if key in telescope_config_struct and key not in ["Tobs"]]
                    KeysCheck = [(key not in telescope_go_params) and (key not in telescope_config_struct) for key in kwargs.keys()]
                    if "Tobs" in kwargs and not np.array_equal(kwargs["Tobs"],telescope_go_params["Tobs"]): # Automatically assume changed if lengths change or values within are not all the same
                        MUTATED=True
                    elif any(ValueCheck1+ValueCheck2+KeysCheck): # Any other value changed?
                        MUTATED=True
                # Check now if there is anything being changed that we can't find in the older saved dict
                from SYNEX.gwemopt_defaults import go_params_default
                from SYNEX.gwemopt_defaults import config_struct_default
                for key,value in kwargs.items(): ### I think this loop can be flattened further but can't find an example right now
                    if key in go_params_default and key not in telescope_go_params and key not in ["NewExistentialFileName","NeworbitFile"]:
                        telescope_go_params[key]=value
                    elif key in go_params_default:
                        telescope_go_params[key]=go_params_default[key]
                    if key in config_struct_default and key not in telescope_config_struct and key not in ["NewExistentialFileName","NeworbitFile"]:
                        telescope_config_struct[key]=value
                    elif key in config_struct_default:
                        telescope_config_struct[key]=config_struct_default[key]
            else:
                # Import default gwemopt dicts
                from SYNEX.gwemopt_defaults import go_params_default as telescope_go_params
                from SYNEX.gwemopt_defaults import config_struct_default as telescope_config_struct
        else:
            # Import default gwemopt dicts
            from SYNEX.gwemopt_defaults import go_params_default as telescope_go_params
            from SYNEX.gwemopt_defaults import config_struct_default as telescope_config_struct

        # Change all things in go_params that are specified in kwargs,
        # and warn the user if any of the things they set are not used...
        print_reminder = False
        for key,value in kwargs.items():
            if key in telescope_go_params:
                telescope_go_params[key]=value
            elif key in telescope_config_struct:
                telescope_config_struct[key]=value
            elif key not in ["NewExistentialFileName","NeworbitFile"]: # Kept like this in case more non-gwemopt keys are added
                if self.verbose: print("Setting new keys '",key,"' in telescope_config_struct...")
                print_reminder = True
                telescope_config_struct[key]=value

        # Check if tesselation file was set
        if telescope_config_struct["tesselationFile"]==None:
            if "ExistentialFileName" in kwargs:
                telescope_config_struct["tesselationFile"]=SYNEX_PATH+"/gwemopt_tess_files"+kwargs["ExistentialFileName"].split("Saved_Telescope_Dicts")[-1]
                telescope_config_struct["tesselationFile"]=".".join(telescope_config_struct["tesselationFile"].split(".")[:-1])+".tess"
            else:
                telescope_config_struct["tesselationFile"]=SYNEX_PATH+"/gwemopt_tess_files/" + telescope_config_struct["telescope"] + ".tess"

        # Check if tesselation file exists and if we want to recompute - otherwise if it exists it will be loaded
        if MUTATED and os.path.isfile(telescope_config_struct["tesselationFile"]):
            if "NewtesselationFile" in kwargs:
                # Take new filename if given
                telescope_config_struct["tesselationFile"] = kwargs["NewtesselationFile"]
            elif "NewExistentialFileName" in kwargs:
                # make a name based on this
                telescope_config_struct["tesselationFile"]=SYNEX_PATH+"/gwemopt_tess_files"+kwargs["NewExistentialFileName"].split("Saved_Telescope_Dicts")[-1]
                telescope_config_struct["tesselationFile"]=".".join(telescope_config_struct["tesselationFile"].split(".")[:-1])+".tess"
            else:
                # No new filename given- create it. NOTE: file extension is checked in 'SYU.GWEMOPTPathChecks()' step below...
                try:
                    # Does it already have an extension number? If so, start there...
                    TessFileExt=telescope_config_struct["tesselationFile"].split("_")[-1] # e.g. '3.tess'
                    TessFileExt = int(TessFileExt.split(".")[0])
                except:
                    # If not,start at 1
                    TessFileExt = 1
                    telescope_config_struct["tesselationFile"] = ".".join(telescope_config_struct["tesselationFile"].split(".")[:-1]) + "_1." + telescope_config_struct["tesselationFile"].split(".")[-1]

                # Find the first version that doesn't exist yet...
                while os.path.isfile(telescope_config_struct["tesselationFile"]):
                    TessFileExt+=1
                    telescope_config_struct["tesselationFile"] = "_".join(telescope_config_struct["tesselationFile"].split("_")[:-1]) + "_" + str(TessFileExt) + "." + telescope_config_struct["tesselationFile"].split(".")[-1]

        # Get/Calculate orbit filename and location
        if not telescope_config_struct["orbitFile"]:
            if self.verbose: print("Creating new orbit file name...")
            t = Time(telescope_config_struct["gps_science_start"], format='gps', scale='utc').isot
            f=SYNEX_PATH+"/orbit_files/"
            pathlib.Path(f).mkdir(parents=True, exist_ok=True)
            orbitFile="Athena_" + "".join(t.split("T")[0].split("-")) + "_" + str(int((telescope_config_struct["mission_duration"]*364.25)//1)) + "d_inc"+str(int(telescope_config_struct["inc"]//1))+"_R"+str(int(telescope_config_struct["MeanRadius"]//1e6))+"Mkm_ecc"+str(int(telescope_config_struct["eccentricity"]//0.1))
            orbitFile+="_ArgPeri"+str(int(telescope_config_struct["ArgPeriapsis"]//1))+"_AscNode"+str(int(telescope_config_struct["AscendingNode"]//1))+"_phi0"+str(int(telescope_config_struct["ArgPeriapsis"]//1))
            orbitFile+="_P"+str(int(telescope_config_struct["period"]//1))+"_frozen"+str(telescope_config_struct["frozenAthena"])+".dat"
            telescope_config_struct["orbitFile"]=f+orbitFile
        if MUTATED and os.path.isfile(telescope_config_struct["orbitFile"]):
            if "NeworbitFile" in kwargs:
                # Take new filename if given
                telescope_config_struct["orbitFile"] = kwargs["NeworbitFile"]
            elif "NewExistentialFileName" in kwargs:
                # make a name based on this
                telescope_config_struct["orbitFile"]=SYNEX_PATH+"/orbit_files"+kwargs["NewExistentialFileName"].split("Saved_Telescope_Dicts")[-1]
                telescope_config_struct["orbitFile"]=".".join(telescope_config_struct["orbitFile"].split(".")[:-1])+".dat"
            else:
                # No new filename given- create it. NOTE: file extension is checked in 'SYU.GWEMOPTPathChecks()' step below...
                try:
                    # Does it already have an extension number? If so, start there...
                    orbitFileExt = telescope_config_struct["orbitFile"].split("_")[-1] # e.g. '3.dat' for '4.config'
                    orbitFileExt = int(orbitFileExt.split(".")[0])
                except:
                    # If not, start at 1
                    orbitFileExt = 1
                    telescope_config_struct["orbitFile"] = ".".join(telescope_config_struct["orbitFile"].split(".")[:-1]) + "_1." + telescope_config_struct["orbitFile"].split(".")[-1]
                # Find the first version that doesn't exist yet...
                while os.path.isfile(telescope_config_struct["orbitFile"]):
                    orbitFileExt+=1
                    telescope_config_struct["orbitFile"] = "_".join(telescope_config_struct["orbitFile"].split("_")[:-1]) + "_" + str(orbitFileExt) + "." + telescope_config_struct["orbitFile"].split(".")[-1]

        # Check that file names up till here are all coherent with SYNEX_PATH and telescope name etc
        telescope_go_params, telescope_config_struct = SYU.GWEMOPTPathChecks(telescope_go_params,telescope_config_struct)

        # Get/Calculate orbit
        # NB : SAVETOFILE=True will force it to recalculate and overwrite any existing 'orbitFile'
        # Unless use_mpi is True (then PermissionToWrite=False), in which case never save so we don't overrun disk quota.
        if not self.PermissionToWrite:
            SAVETOFILE=False
        elif MUTATED or not os.path.isfile(telescope_config_struct["orbitFile"]):
            SAVETOFILE=True
        else:
            SAVETOFILE=False
        import SYNEX.segments_athena as segs_a
        orbitFilePath="/".join(telescope_config_struct["orbitFile"].split("/")[:-1])
        pathlib.Path(orbitFilePath).mkdir(parents=True, exist_ok=True)
        telescope_config_struct = segs_a.get_telescope_orbit(telescope_config_struct,SAVETOFILE=SAVETOFILE,verbose=self.verbose)

        # Set as class attributes
        self.telescope_go_params = telescope_go_params
        self.telescope_config_struct = telescope_config_struct
        if MUTATED:
            # Force this to be None if we changed something while resurrecting a class
            self.telescope_source_coverage=None
        else:
            self.telescope_source_coverage=telescope_source_coverage
        if MUTATED:
            # Force this to be None if we changed something while resurrecting a class
            self.telescope_tile_struct=None
        else:
            self.telescope_tile_struct=telescope_tile_struct
        if MUTATED:
            # Force this to be None if we changed something while resurrecting a class
            self.telescope_tile_struct=None
        else:
            self.telescope_tile_struct=telescope_tile_struct

        # Set save file name if not already there
        if not hasattr(self,"ExistentialFileName"):
            ExistentialFile=SYNEX_PATH+"/Saved_Telescope_Dicts"+self.telescope_config_struct["tesselationFile"].split("gwemopt_tess_files")[-1]
            ExistentialFile=".".join(ExistentialFile.split(".")[:-1])+".dat"
            self.ExistentialFileName=ExistentialFile

        # If we resurrected with mutation, keep a reference to where this class came from
        if MUTATED:
            self.MutatedFromTelescopeFile = self.ExistentialFileName
            if "NewExistentialFileName" in kwargs:
                # Take new filename if given
                self.ExistentialFileName = kwargs["NewExistentialFileName"]
            else:
                # No new filename given- create it. NOTE: file extension left ambiguous
                try:
                    # Does it already have an extension number? If so, start there...
                    ExistentialFileExt = self.ExistentialFileName.split("_")[-1] # e.g. '3.dat' for '4.config'
                    ExistentialFileExt = int(ExistentialFileExt.split(".")[0])
                except:
                    # If not, start at 1
                    ExistentialFileExt = 1
                    self.ExistentialFileName = ".".join(self.ExistentialFileName.split(".")[:-1]) + "_1." + self.ExistentialFileName.split(".")[-1]

                # Find the first version that doesn't exist yet...
                while os.path.isfile(self.ExistentialFileName):
                    ExistentialFileExt+=1
                    self.ExistentialFileName = "_".join(self.ExistentialFileName.split("_")[:-1]) + "_" + str(ExistentialFileExt) + "." + self.ExistentialFileName.split(".")[-1]
            if self.verbose: print("Successfully mutated telescope:", self.MutatedFromTelescopeFile)
            if self.verbose: print("New savefile for mutation:", self.ExistentialFileName)

        # Check that file paths exist - in case of subdirectory organizational architectures...
        # Tesselation path already checked in 'SYU.GWEMOPTPathChecks()'
        ExistentialPath="/".join(self.ExistentialFileName.split("/")[:-1])
        pathlib.Path(ExistentialPath).mkdir(parents=True, exist_ok=True)

        # Calculate tesselation - telescope is saved at the end of this in case we recompute in other codes
        # If 'MUTATED' was False then if the '.tess' file exists the tesselation will be loaded.
        self.ComputeTesselation()

        # Hardcode ARF file for now -- to include later as option
        self.ARF_file_loc_name=SYNEX_PATH+"/XIFU_CC_BASELINECONF_2018_10_10.arf"

        # Issue reminder of where to find list of gwemopt variables and flags
        if print_reminder and self.verbose:
            print("Some keys given at initiatiation of Athena class are not contained in gwemop params - see 'SYNEX/gwemopt_defaults.py' for full list of possible field names.")

    def ComputeTesselation(self):
        if self.telescope_go_params["doSingleExposure"]:
            # exposuretime = np.array(self.telescope_go_params["exposuretimes"].split(","),dtype=np.float)[0]
            if "exposuretimes" in self.telescope_go_params:
                exposuretime = np.array(self.telescope_go_params["exposuretimes"].split(","),dtype=np.float)[0]
            else:
                exposuretime=self.telescope_config_struct["exposuretime"]
            nmag = -2.5*np.log10(np.sqrt(self.telescope_config_struct["exposuretime"]/exposuretime))
            self.telescope_config_struct["magnitude"] = self.telescope_config_struct["magnitude"] + nmag
            self.telescope_config_struct["exposuretime"] = exposuretime
        if "tesselationFile" in self.telescope_config_struct:
            # if not os.path.isfile(self.telescope_config_struct["tesselationFile"]):
            if self.telescope_config_struct["FOV_type"] == "circle":
                ras,decs=gwemopt.tiles.tesselation_spiral(self.telescope_config_struct,WriteToFile=self.PermissionToWrite)
            elif self.telescope_config_struct["FOV_type"] == "square":
                ras,decs=gwemopt.tiles.tesselation_packing(self.telescope_config_struct,WriteToFile=self.PermissionToWrite)
            if self.telescope_go_params["tilesType"] == "galaxy":
                self.telescope_config_struct["tesselation"] = np.empty((3,))
            else:
                # self.telescope_config_struct["tesselation"] = np.loadtxt(self.telescope_config_struct["tesselationFile"],usecols=(0,1,2),comments='%')
                self.telescope_config_struct["tesselation"] = np.array([[ii,radec[0],radec[1]] for ii,radec in enumerate(zip(ras,decs))])

        if "referenceFile" in self.telescope_config_struct: ### Not sure what this is but we include it to be complete with GWEMOPT
            from astropy import table
            refs = table.unique(table.Table.read(
                self.telescope_config_struct["referenceFile"],
                format='ascii', data_start=2, data_end=-1)['field', 'fid'])
            reference_images =\
                {group[0]['field']: group['fid'].astype(int).tolist()
                for group in refs.group_by('field').groups}
            reference_images_map = {1: 'g', 2: 'r', 3: 'i'}
            for key in reference_images:
                reference_images[key] = [reference_images_map.get(n, n)
                                         for n in reference_images[key]]
            self.telescope_config_struct["reference_images"] = reference_images

        # Save it all to file!
        self.ExistentialCrisis()

    def GetKuiper(self, TilePickleFile, source=None):
        """
        ################# This function is no longer frequently used #################

        # Figure out maximum times we can do in the time available
        # Will include time slew as an extra exit flag in the loop over tiles,
        # cutting out the last m tiles (m<n) once the slew time consumes the equivalent time for m tiles.
        # Define the time to merger

        ################# This function is no longer frequently used #################
        """
        # Get tiles from json file
        with open(TilePickleFile, 'rb') as f:
            TileDict = pickle.load(f)

        H5FileLocAndName = TileDict["LISA Data File"]
        json_file,H5FileLocAndName=SYU.CompleteLisabetaDataAndJsonFileNames(LISAPosteriorDataFile)
        with open(json_file, 'r') as f:
            input_params = json.load(f)
        f.close()

        T_s = source.xray_time[0]
        if T_s>input_params["waveform_params"]["DeltatL_cut"]:
            TimeToMerger = T_s
        else:
            TimeToMerger = input_params["waveform_params"]["DeltatL_cut"]
        n_times = int(-TimeToMerger//self.T_lat)
        if self.verbose: print(n_times, "tiles in remaining time to merger...")

        # Sort the dictionary to contain just the tiles we want
        Extra_keys = ["Tile Strat", "overlap", "LISA Data File", "source_EM_properties", "tile_structs", "go_params", "map_struct"]
        if TileDict["Tile Strat"]=="MaxProb":
            TileDict_reduced = {k: v for k, v in TileDict.items() if k not in Extra_keys and int(k)<n_times}
        else:
            for telescope in TileDict["tile_structs"].keys(): ######### NEED TO ADJUST THIS SO WE CAN HANDLE SEVERAL TELESCOPE INSTANCES... MAYBE WE DON'T NEED TO AND WE CAN FOCUS ON SEVERAL TILING METHODS AT A TIME INSTEAD?
                TileDict_reduced = {k: v for k, v in TileDict["tile_structs"][telescope].items() if int(k)<n_times} ######## I THINK YOU CAN REDUCE COMLEXITY HERE IF WE CAN FEED N_TILES DIRECTLY INTO GWEMOPT- IT HAS A PARAM IN go_params THAT INDICATES HOW MANY TILES TO CALCULATE...
        max_key = [int(k) for k in TileDict_reduced.keys()]
        max_key = max(max_key)
        if max_key<n_times:
            n_times = max_key
        self.tileIDs = [int(k) for k in TileDict_reduced.keys()]
        self.tile_times = [(ID-0.5)*self.T_lat+TimeToMerger for ID in self.tileIDs] # + slew dead time! ### This is the central time

        # Get photon arrival times, cut the majority of the xray time and CTR since we will start tiling at time_to_merger
        from scipy.stats import uniform
        from astropy.stats import kuiper,kuiper_two
        from functools import partial
        import random
        xray_time_merger = [time for time in source.xray_time if time>=TimeToMerger]
        xray_flux_merger = [f for (time,f) in zip(source.xray_time,source.xray_flux) if time>=TimeToMerger]
        phi_merger = [phi/2. for (time,phi) in zip(source.xray_time,source.GW_phi) if time>=TimeToMerger] # Should be orbital phase NOT GW... They say in the paper that they just 'infer' the phi_is from the measured gravitational wave phase evolution
        # phi_merger = [random.random()*2.*np.pi for ii in range(len(phi_merger))]
        # Omega_merger = [Om for (time,Om) in zip(source.xray_time,source.GW_Omega) if time>=TimeToMerger]
        CTR_merger = [CTR for (time,CTR) in zip(source.xray_time,source.CTR) if time>=TimeToMerger]
        # CTR_merger = [np.sin(2.*np.pi*0.0001*time)+1.5 for time in xray_time_merger]
        CTR_sum = sum(CTR_merger)
        probs_merger = [CTR/CTR_sum for CTR in CTR_merger]
        n_photons = int(np.trapz(CTR_merger,xray_time_merger))
        ts = xray_time_merger[0]
        te = ts + self.T_lat

        t_is_merger = np.random.choice(xray_time_merger, n_photons, p=probs_merger).tolist()
        t_is_merger.sort()

        two_pi = 2.*np.pi
        f = scipy.interpolate.interp1d(xray_time_merger,phi_merger) # Omega_merger) #
        phi_is_merger = list(f(t_is_merger)) # [2.*np.pi*0.0001*time for time in t_is_merger]

        # Add backgrounds
        ADD_BACKGROUND = True
        if ADD_BACKGROUND:
            import random
            CTR_bg = [7.4e-5]*len(CTR_merger) # 7.4e-5
            n_bg_photons = int(np.trapz(CTR_bg,xray_time_merger))
            if self.verbose: print(n_bg_photons, "background photons added to the whole x-ray timeseries...")
            max_time = -xray_time_merger[0]
            time_lim = [time-xray_time_merger[0] for (time,CTR) in zip(xray_time_merger,CTR_merger) if CTR>0]
            time_lim = time_lim[-1]
            t_is_bg = [random.random()*time_lim-max_time for ii in range(n_bg_photons)] # np.random.choice(xray_time_merger, n_bg_photons).tolist() # default is uniform
            t_is_bg.sort()
            t_is_merger+=t_is_bg
            rand_angles = [random.random()*two_pi for ii in range(n_bg_photons)] # default is uniform
            phi_is_merger+=rand_angles

        bin_pops,bins=np.histogram([p_i%two_pi for p_i in phi_is_merger],bins=100) # int(len(phi_is_merger)/10)
        bin_centres = [bins[ii]+0.5*(bins[1]-bins[0]) for ii in range(len(bins)-1)]
        bin_pops_normed = [bin_pops[ii]/sum(bin_pops) for ii in range(len(bin_pops))]
        bin_pops_normed_cumsum = [sum(bin_pops_normed[:ii]) for ii in range(len(bin_pops_normed))]
        bin_pops_normed_mean = np.mean(bin_pops_normed)
        probs_merger_mean = np.mean(probs_merger)

        ###########    THIS NEEDS CLEANING UP !!    ###########
        kuipers = [0.1]
        self.n_photons = []
        self.n_exposures = 0
        exposure_photons = 0
        exposure_t_is = []
        exposure_phi_is = []
        self.exposure_tiles = []
        self.exposure_xray_time = []
        self.exposure_CTR = []
        self.exposure_tile_probs = []
        self.tile_kuiper_p_val_trace = []
        self.exposure_kuiper_trace = []
        self.exposure_kuiper_p_val_trace = []
        self.detection_kuiper_p_val_trace = []
        self.exposure_tile_xray_time = []
        self.exposure_tile_CTR = []
        self.exposure_tile_probs = []
        self.accum_exposure_photons_trace = []
        self.exposure_photons_trace = []
        self.tile_detection_p_val_trace = []
        exposure_kuiper = 0.01
        exposure_p_val = 1.
        tile_p_val = 1.
        n_photons = 0
        import time
        from operator import add
        t0 = time.time()
        for tile in TileDict_reduced:
            # See if the tile includes the source - update the statistics for the source
            if source.beta<TileDict_reduced[tile]['beta_range'][1] and source.beta>TileDict_reduced[tile]['beta_range'][0] and source.lamda<TileDict_reduced[tile]['lambda_range'][1] and source.lamda>TileDict_reduced[tile]['lambda_range'][0]: # 1: #
                # Calculate tile statistical properties
                tile_CTR = [CTR for (CTR,time) in zip(CTR_merger,xray_time_merger) if time>ts and time<te]
                tile_xray_time = [time for time in xray_time_merger if time>=ts and time<=te]
                t_is = [t_i_merger for t_i_merger in t_is_merger if t_i_merger>ts and t_i_merger<te]
                phi_is = [phi_i%two_pi for (phi_i,time) in zip(phi_is_merger,t_is_merger) if time>ts and time<te]
                n_photons = len(t_is)
                self.n_photons.append(n_photons)

                tile_kuiper, tile_p_val = kuiper(phi_is, partial(uniform.cdf, loc=0.,scale=two_pi)) # loc=min(phi_is),scale=max(phi_is)-min(phi_is))) #
                kuipers.append(tile_kuiper)

                # Update exposure statistics
                self.n_exposures+=1
                self.exposure_tiles.append(int(tile))
                exposure_photons += n_photons
                exposure_t_is += t_is
                exposure_phi_is += phi_is
                bin_pops, bins = np.histogram(exposure_phi_is,bins=np.linspace(0.,two_pi,50))
                bin_centres = [bins[ii]+0.5*(bins[1]-bins[0]) for ii in range(len(bins)-1)]
                s_phi = [bin_pops[ii]/sum(bin_pops) for ii in range(len(bin_pops))]
                S_phi = [sum(s_phi[:ii]) for ii in range(len(s_phi))]
                U_phi = [ii/len(bin_centres) for ii in range(len(bin_centres))]
                exposure_kuiper, exposure_p_val = kuiper(exposure_phi_is, partial(uniform.cdf, loc=0.,scale=two_pi))

                if self.n_exposures>0:
                    detection_p_val = 1.-(1.-exposure_p_val)**(self.n_exposures*518400)
                    tile_detection_p_val = 1.-(1.-tile_p_val)**(self.n_exposures*518400)
                else:
                    detection_p_val = 1.-(1.-exposure_p_val)
                    tile_detection_p_val = 1.-(1.-tile_p_val)
                if self.verbose: print("Tile:", tile, self.n_exposures, n_photons, len(exposure_phi_is), tile_kuiper, tile_p_val, exposure_kuiper, exposure_p_val, detection_p_val)

            # Update the traced properties
            self.tile_kuiper_p_val_trace.append(tile_p_val)
            self.tile_detection_p_val_trace.append(tile_detection_p_val)
            self.exposure_kuiper_trace.append(exposure_kuiper)
            self.exposure_kuiper_p_val_trace.append(exposure_p_val)
            self.detection_kuiper_p_val_trace.append(detection_p_val)
            self.accum_exposure_photons_trace.append(exposure_photons)
            self.exposure_photons_trace.append(n_photons)

            # Update the start and end times for the tile latency
            ts = te # + slew time
            te = ts + self.T_lat # times are in seconds to merger

        # exposures
        if self.verbose: print(self.n_exposures, "exposures of source by tiles", self.exposure_tiles, "using", TileDict["Tile Strat"], "tiling strategy.")
        # if self.verbose: print("Total photons:", sum(self.n_photons), "with", sum(self.n_photons[:-1]), "exposure photons and", self.n_photons[-1],"background photons.")
        if self.verbose: print("Accumulated photons during on-source exposures (S+B):", sum(self.n_photons))
    
    def ExistentialCrisis(self,NewFileName=None):
        """
        Function to save all class attributes as a dictionary to file,
        making sure to overwrite existing files by the same name. This will
        make source resurrection easier if we do a long analysis run in stages.

        NB: When we get to tiling attributes may not be serializable for json files,
        so here we opt for pickling to '.dat' files instead.
        However, we do not check that the new 'FileName' has the right extension
        or path. Need to do this later.
        """
        if NewFileName!=None:
            # Check new filepath exists...
            NewFilePath="/".join(NewFileName.split("/")[:-1])
            pathlib.Path(NewFilePath).mkdir(parents=True, exist_ok=True)
            # Reset name in class attributes
            self.ExistentialFileName = NewFileName
        # Gather attributes to dict
        MyExistentialDict = copy.deepcopy(self.__dict__)
        # Remove orbit and tesselation that are always recalculated at init
        del MyExistentialDict["telescope_config_struct"]["orbit_dict"]
        del MyExistentialDict["telescope_config_struct"]["tesselation"]
        # Save to file...
        if self.verbose: print("Saving telescope attributes to:",self.ExistentialFileName)
        with open(self.ExistentialFileName, 'wb') as f:
            pickle.dump(MyExistentialDict, f)
        if self.verbose: print("Done.")
