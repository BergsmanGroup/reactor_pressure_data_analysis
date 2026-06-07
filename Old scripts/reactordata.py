import os
import pickle
import file_handling
import data_processing
import plotting
import warnings
import copy
import matplotlib.pyplot as plt
import matplotlib.image as mpimg
import pandas as pd


def ANSIprint(color, text):
    color = color.lower()
    ASCI_escape_dict = {
        'black': '30m',
        'red': '31m',
        'green': '32m',
        'yellow': '33m',
        'blue': '34m',
        'magenta': '35m',
        'cyan': '36m',
        'white': '37m'
    }
    color_code = ASCI_escape_dict.get(color, '37m')
    print(f"\033[{color_code}{text}\033[0m")


class ReactorData:
    def __init__(self, abspath=None,valve_dict=None):
        print('Getting source file info')
        self.sourceinfo_dict = {}
        if abspath is None:
            print('Prompting user for source via file dialog')
            self.sourceinfo_dict = file_handling.sourceinfo_easygui()
        else:
            print(f"Splitting source info from provided filepath {abspath}")
            self.sourceinfo_dict = file_handling.sourceinfo_abspath(abspath)
        #ANSIprint('green', 'Source info loaded to instance:')

        self.warnings = {}
        if self.sourceinfo_dict['file_ext'] == '.json':
            self._initialize_from_json(valve_dict)
        elif self.sourceinfo_dict['file_ext'] == '.pkl':
            self._initialize_from_pickle()

    def _initialize_from_json(self,valve_dict=None):
        self.fig_dict = {}
        self.shift = 0
        print('Initializing from json')
        self.df, self.header, self.footer = data_processing.load_reactor_json(self.sourceinfo_dict['file_path'])
        self.warnings.update(data_processing.check_header_footer(self.header, self.footer))
        ANSIprint('green', 'Dataframe loaded from json')
        ANSIprint('green', 'Initializing dictionaries')
        self.df_dict = {}
        self.df_dict['original'] = copy.deepcopy(self.df)
        self.fig_dict = {}
        ANSIprint('green', 'Re-typing cycles and pressure columns as int and float, respectively')
        self.df['cycle'] = self.df['cycle'].astype(int)
        self.df['pressure'] = self.df['pressure'].astype(float)
        ANSIprint('green', 'Converting sequence LOLI to dictionary')
        self.header['payload']['valveSequence'] = data_processing.convert_sequence(self.header['payload']['valveSequence'])
        ANSIprint('green', 'Generating sequence detail columns')
        #print(self.header['payload']['valveSequence'])
        self.df = data_processing.generate_sequencedetail_columns(self.df, self.header['payload']['valveSequence'])
        ANSIprint('green', 'Cutting by phases')
        self.df, self.header['payload']['valveSequence'] = data_processing.cut_by_phases(self.df, self.header['payload']['valveSequence'], self.shift)
        self.header['payload']['totals'] = {}
        self.header['payload']['totals']['expected'] = data_processing.total_expected_cycles(self.header['payload']['valveSequence'])
        self.header['payload']['totals']['executed'] = self.df['cycle'].max()
        self.header['payload']['totals']['ylim'] = self.df['pressure'].max()
        self.header['payload']['totals']['ymin'] = self.df['pressure'].min()
        self.df['pressure'] = self.df['pressure']-self.header['payload']['totals']['ymin']
        self.header['payload']['totals']['xlim'] = self.df[self.df['cycle']>1]['cycle_time'].max()
        executed = self.header['payload']['totals']['executed']
        expected = self.header['payload']['totals']['expected']
        if executed < expected:
            warnings.warn(f"Recipe did not fully execute. {executed}/{expected} cycles executed")
            self.warnings['Recipe completion'] = f"Did not fully execute. {executed}/{expected} cycles executed"
        elif executed > expected:
            warnings.warn(f"Extra cycles recorded. {executed}/{expected} cycles executed")
            self.warnings['Recipe completion'] = f"Extra cycles recorded. {executed}/{expected} cycles executed"
        elif executed == expected:
            print(f"Recipe fully executed. {executed}/{expected} cycles executed")
        if valve_dict != None:
            self.set_phase_names(valve_dict=valve_dict)
        self.df_dict['initialized'] = copy.deepcopy(self.df)
        print('Calculating integrals')
        self.df_dict['integrals'] = data_processing.calculate_integral(self.df)
        ANSIprint('red',f"Save instance as pkl? (will overwrite existing file: {self.sourceinfo_dict['pickle_name']})")
        if self._get_yes_no_input():
            self.save()


    def plot_integrated_barchart(self,ylim=[None,None]):
        fig = plotting.plot_integrated_barchart(self.df_dict['integrals'],ylim,title=self.sourceinfo_dict['file_name'])
        targetdirectory = file_handling.directory_explorer()
        fig_path = os.path.join(targetdirectory,f"{self.sourceinfo_dict['file_name']}_integrated_exposure.png")
        fig.savefig(fig_path)
        plt.close()
        img = mpimg.imread(fig_path)
        plt.imshow(img)
        plt.axis('off')
        plt.show()


    def save(self,dialog=False):
        if dialog == True:
            save_directory = file_handling.directory_explorer()
        elif dialog == False:
            save_directory = self.sourceinfo_dict['file_directory']
        with open(f"{save_directory}\\{self.sourceinfo_dict['pickle_name']}",'wb') as file:
            pickle.dump(self,file)


    def _initialize_from_pickle(self):
        try:
            with open(self.sourceinfo_dict['file_path'], 'rb') as file:
                sourceinfo_dict = self.sourceinfo_dict
                loaded_instance = pickle.load(file)
                self.__dict__.update(loaded_instance.__dict__)
                self.sourceinfo_dict = sourceinfo_dict
                #if self.compatibility != self.version:
                #    warnings.warn(f"Code compatibility ({self.compatibility}) does not match pkl version ({self.version})")
                #    self.warnings['Compatibility'] = f"Code compatibility ({self.compatibility}) does not match pkl version ({self.version})'
        except Exception as e:
            print(f"Error loading from pickle: {e}")

    def _get_input_list(self,prompt='Enter list elements separated by commas: ', data_type=int):
        """
        Prompts the user for a list of elements separated by commas and converts them to the specified data type.

        Parameters:
        - prompt: The prompt to display to the user.
        - data_type: The type to which each element should be converted (default is str).

        Returns:
        - A list of elements converted to the specified data type, or None if the input is empty.
        """
        input_string = input(prompt).strip()
        
        # Return None if the input is empty
        if not input_string:
            return None
        
        # Split the input string into a list
        listy = input_string.split(',')
        
        # Strip any leading/trailing whitespace from each element
        listy = [element.strip() for element in listy]
        
        # Convert elements to the specified data type
        try:
            listy = [data_type(element) for element in listy]
        except ValueError as e:
            print(f"Error converting elements to {data_type.__name__}: {e}")
            return None
        
        return listy

    def _get_single_input(self,prompt='Enter a value: ', data_type=str):
        """
        Prompts the user for a single value and converts it to the specified data type.

        Parameters:
        - prompt: The prompt to display to the user.
        - data_type: The type to which the value should be converted (default is str).

        Returns:
        - The value converted to the specified data type, or None if the input is empty or conversion fails.
        """
        input_string = input(prompt).strip()
        
        # Return None if the input is empty
        if not input_string:
            return None
        
        # Convert the input to the specified data type
        try:
            value = data_type(input_string)
        except ValueError as e:
            print(f"Error converting input to {data_type.__name__}: {e}")
            return None
        
        return value

    def _get_yes_no_input(self,prompt='Enter yes or no (or true or false): '):
        """
        Prompts the user for a 'yes', 'no', 'true', or 'false' input and returns True or False.

        Parameters:
        - prompt: The prompt to display to the user.

        Returns:
        - True if the user inputs 'yes', 'y', 'true', or 't'.
        - False if the user inputs 'no', 'n', 'false', or 'f'.
        - None if the input is invalid.
        """
        valid_responses = {
            'yes': True, 'y': True, 'true': True, 't': True,
            'no': False, 'n': False, 'false': False, 'f': False
        }
        
        while True:
            user_input = input(prompt).strip().lower()
            
            if user_input in valid_responses:
                return valid_responses[user_input]
            else:
                print("Invalid input. Please enter 'yes', 'no', 'true', 'false', or their abbreviations.")



    def plot_static(self,cycles,filename,df,xlim,ylim,title,retfig,showfig):
    #    cycles = self._get_input_list('Enter cycle list separated by commas: ',data_type=int)
    #    if not cycles:
    #        cycles = list(range(1,self.df['cycle'].max()+1))
    #    filename = self.sourceinfo_dict['file_name']
    #    df = self.df
    #    xlim = self._get_input_list('Enter xlim separated by commas, or press enter for default: ',data_type=float)
    #    ylim = self._get_input_list('Enter ylim separated by commas, or perss enter for detault: ',data_type=float)
    #    if not xlim:
    #        xlim = [None,None]
    #    if not ylim:
    #        ylim = [None,None]
    #    title = self._get_input_list('Enter title, or press enter for default: ',data_type=str)
    #    if not title:
    #        title = 'default'
    #    retfig = self._get_yes_no_input('Add figures to dictionary? (y/n): ')
    #    showfig = self._get_yes_no_input('Show figures? (y/n): ')
        fig_dict = plotting.static_cycles(cycles,filename,df,xlim,ylim,title,retfig,showfig)
        self.fig_dict.update(fig_dict)

    def plot_static_interactive(self):
        cycles = self._get_input_list('Enter cycle list separated by commas: ',data_type=int)
        if not cycles:
            cycles = list(range(1,self.df['cycle'].max()+1))
        filename = self.sourceinfo_dict['file_name']
        df = self.df
        xlim = self._get_input_list('Enter xlim separated by commas, or press enter for default: ',data_type=float)
        ylim = self._get_input_list('Enter ylim separated by commas, or perss enter for detault: ',data_type=float)
        if not xlim:
            xlim = [None,None]
        if not ylim:
            ylim = [None,None]
        title = self._get_input_list('Enter title, or press enter for default: ',data_type=str)
        if not title:
            title = 'default'
        retfig = self._get_yes_no_input('Add figures to dictionary? (y/n): ')
        showfig = self._get_yes_no_input('Show figures? (y/n): ')
        fig_dict = plotting.static_cycles(cycles,filename,df,xlim,ylim,title,retfig,showfig)
        if retfig:
            self.fig_dict.update(fig_dict) 

    def generate_animation(self,spf=0.25):
        targetdirectory = f"{self.sourceinfo_dict['file_directory']}\\{self.sourceinfo_dict['file_name']}_animation"
        plotting.generate_animation(self.fig_dict,targetdirectory,spf)

#    def set_phase_names(self, valve_dict):
#        """
#        Update the phase names for sequences by replacing valve names using a provided dictionary.
#        """
#        # Iterate over all sequences
#        for seq_key, sequence in self.header['payload']['valveSequence'].items():
#            print(f"Defining phase names for sequence {seq_key}:")
#            
#            # Iterate over all phases in the list
#            for idx, phase_name in enumerate(sequence['phase_names']):
#                parts = phase_name.split('_')
#                
#                if len(parts) >= 2 and parts[1] in valve_dict:
#                    old_valve_name = parts[1]
#                    new_valve_name = valve_dict[old_valve_name]
#                    new_phase_name = f"{parts[0]}_{new_valve_name}_{parts[2]}"
#                    sequence['phase_names'][idx] = new_phase_name
#                    
#                    print(f"Updated phase {idx + 1}: '{phase_name}' to '{new_phase_name}'")
#                    
#                    # Also update the DataFrame directly if needed
#                    self.df.loc[self.df['phase'] == phase_name, 'phase'] = new_phase_name
#                    
#                else:
#                    print(f"No update for phase {idx + 1}: '{phase_name}'")
#            
#            print(f"Phase names updated for sequence {seq_key}.")

    def set_phase_names(self, valve_dict):
        """
        Update the phase names for sequences by replacing valve names using a provided dictionary.
        """
        # Store unique phase names for setting categorical type later
        unique_phases = set()

        # Iterate over all sequences
        for seq_key, sequence in self.header['payload']['valveSequence'].items():
            print(f"Defining phase names for sequence {seq_key}:")

            # Iterate over all phases in the list
            for idx, phase_name in enumerate(sequence['phase_names']):
                parts = phase_name.split('_')

                if len(parts) >= 2 and parts[1] in valve_dict:
                    old_valve_name = parts[1]
                    new_valve_name = valve_dict[old_valve_name]
                    new_phase_name = f"{parts[0]}_{new_valve_name}_{parts[2]}"
                    sequence['phase_names'][idx] = new_phase_name
                    unique_phases.add(new_phase_name)  # Add to unique phase set

                    print(f"Updated phase {idx + 1}: '{phase_name}' to '{new_phase_name}'")

                    # Update categories in DataFrame if needed
                    self.df['phase'] = self.df['phase'].astype('category')
                    if new_phase_name not in self.df['phase'].cat.categories:
                        self.df['phase'] = self.df['phase'].cat.add_categories([new_phase_name])

                    # Update the DataFrame directly
                    self.df.loc[self.df['phase'] == phase_name, 'phase'] = new_phase_name

                else:
                    unique_phases.add(phase_name)  # Add to unique phase set if not updated
                    print(f"No update for phase {idx + 1}: '{phase_name}'")

            print(f"Phase names updated for sequence {seq_key}.")

        # Set the 'phase' column to categorical with unique phases as categories
        self.df['phase'] = pd.Categorical(self.df['phase'], categories=sorted(unique_phases))
        print("DataFrame 'phase' column updated to categorical data type.")

