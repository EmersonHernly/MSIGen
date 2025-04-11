"""This module provides a function to subclass the base MSIGen object for different file formats."""

import importlib
import os

class msigen(object):
    def __new__(cls, *args, **kwargs):
        """
        This function subclasses the base MSIGen object for different file formats.
        
        Parameters:
        example_file (str or list): The file path or list of file paths to be processed.
        *args: Additional positional arguments for the subclass.
        **kwargs: Additional keyword arguments for the subclass.
        
        Returns:
        An instance of the appropriate class based on the file format.
        """
        if "example_file" in kwargs:
            example_file = kwargs["example_file"]
        elif len(args) > 0:
            example_file = args[1]
        else:
            example_file = None

        # Initialize the base class without data files if example_file is None
        if example_file is None:
            module = importlib.import_module('base_class', package='MSIGen')
            return module.MSIGen_base(*args, **kwargs)
        
        # Check the file extension of the example_file and load the appropriate module
        if type(example_file) == str:
            file_extension = os.path.splitext(example_file)[1].lower()
        if type(example_file) in [list, tuple]:
            file_extension = os.path.splitext(example_file[0])[-1].lower()
            
        if file_extension == ".d":  # Customize extension matching as needed
            module = importlib.import_module('D', package='MSIGen')
            return module.MSIGen_D(*args, **kwargs)
        elif file_extension == ".raw":
            module = importlib.import_module('raw', package='MSIGen')
            return module.MSIGen_raw(*args, **kwargs)
        elif file_extension == ".mzml":
            module = importlib.import_module('mzml', package='MSIGen')
            return module.MSIGen_mzml(*args, **kwargs)
        else:
            raise ValueError(f"Invalid file extension{file_extension}. Supported file extensions are: '.d', '.mzml', '.raw'")

    @classmethod
    def load_pixels(cls, path=None):
        """
        This function loads pixel data from the specified file without initilizing the class beforehand.
        
        Parameters:
        path (str): The file path to load pixel data from.

        Returns:
        Pixel data loaded from the file.
        """
        # Load the base class module and call the load_pixels method
        module = importlib.import_module('base_class', package='MSIGen')
        return module.MSIGen_base().load_pixels(path)