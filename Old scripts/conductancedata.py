import tkinter as tk
import os
import pickle
import numpy as np
import matplotlib.pyplot as plt
import numbers
horizontal_line = '-' * 126
import data_processing_conductance

class conductance_data:
    
    """
    Default args: 
        reducedHz=5000, debugon=False, switchvcorder=False, flip=False, vier=False
        input list of the form [5000, False, False, False, False]
    """
    def __init__(self,conductivity=29,pH=8,thickness=35,nominal_diameter=20,T_f=1,
                 file_path='Tkinter',args=[5000, False, False, False, False]):

        """
        conductance: conductance of electrolyte in nS/nm. Conversion factor for mS/cm is *0.1
        Thickness: thickness of nanopore membrane
        nominal_diameter: nominal diameter of nanopore
        filepath: default "tkinter" opens file dialog to browse for file. 
        
        
        """

        print('\n',horizontal_line)
        print('Initializing...')
        if file_path == 'Tkinter':
            self.file_path, self.file_name, self.file_ext = self.get_filepath()          
        else:
            self.file_path = file_path
            self.file_name, self.file_ext = os.path.splitext(self.file_path)
            self.file_name = os.path.basename(self.file_name)
            self.file_ext = os.path.basename(self.file_ext)
        self.regress_dict = {}
        self.conductivity = conductivity
        self.thickness = thickness
        self.nominal_diameter = nominal_diameter
        self.T_f=1
                
        print('file_path=',self.file_path)
        print()
        print('name=',self.file_name)
        if self.file_ext == '.pkl':
            # Load data from pickle. Should include df, metadata, and regress dictionaries
            # Function args for cond, ph, thickness, nominal diameter, T_f will be overwritten
            print('Filetype: .pkl')
            self.load_from_pickle()
            self.time = np.nanmax(self.df['Time'])
        elif self.file_ext== '.dat':
            print('Processing .dat file')
            self.df, self.metadata_dict = data_processing_conductance.process_file(self.file_path, reducedHz=args[0], debugon=args[1], switchvcorder=args[2], flip=args[3], vier=args[4])
            print(self.metadata_dict)
            self.time = np.nanmax(self.df['Time'])
            self.metadata_dict['conductivity'] = conductivity
            self.metadata_dict['pH'] = pH
            self.metadata_dict['thickness'] = thickness
            self.metadata_dict['nominal_diameter'] = nominal_diameter
            self.metadata_dict['T_f'] = T_f
    
    def add_diameter_column(self,remove_values_at_0=True):
        print('\n',horizontal_line)
        print('Adding diameter column')
        print('Loading variables for diameter calculation')
        S=self.metadata_dict['conductivity']
        if S > 15:
            print('S=',S,'mS/cm')
            S = S/10            
        else:
            print('S=',S,'nS/cm')
        T=self.metadata_dict['thickness']
        print('T=',T,'nm')
        T_f=self.metadata_dict['T_f']
        print('Thickness factor=',T_f)
        pi = np.pi
        sqrt = np.sqrt
        print('Adding diameter column')
        self.df['Diameter'] = (sqrt(pi)*sqrt(pi*(self.df['Current']/self.df['Voltage'])**2+16*(self.df['Current']/self.df['Voltage'])*S*T)+pi*(self.df['Current']/self.df['Voltage']))/(2*pi*S)
        if remove_values_at_0 == True:
            print('Removing diameter values at I=0')
            # Generate boolean array indicating where 'Column3' is close to 0 within the tolerance
            is_close_to_zero = np.isclose(self.df['Voltage'], 0, atol=20)
            # Get the indices where 'Column3' is close to 0
            indices_to_drop = self.df.index[is_close_to_zero].tolist()
            # Drop values in 'Column3' at those indices
            self.df.loc[indices_to_drop, 'Diameter'] = None
        else:
            print('Removing diameter values at I=0')
            pass
    
    def add_G_column(self,remove_values_at_0=True):
        print('\n',horizontal_line)
        print('Adding G column')
        self.df['G'] = self.df['Current']/self.df['Voltage']
        if remove_values_at_0 == True:
            print('Removing G values at I=0')
            # Generate boolean array indicating where 'Column3' is close to 0 within the tolerance
            is_close_to_zero = np.isclose(self.df['Current'], 0, atol=50)
            # Get the indices where 'Column3' is close to 0
            indices_to_drop = self.df.index[is_close_to_zero].tolist()
            # Drop values in 'Column3' at those indices
            self.df.loc[indices_to_drop, 'G'] = None
        else:
            print('Leaving G values at I=0')
            pass
    
    def get_filepath(self):
        window = tk.Tk()
        file = filedialog.askopenfile(mode='r')
        file_path = os.path.abspath(file.name)
        file_name, file_ext = os.path.splitext(file_path)
        file_name = os.path.basename(file_name)
        window.destroy()
        window.mainloop()
        return file_path, file_name, file_ext
    
    def get_folder(self):
        window = tk.Tk()
        directory = filedialog.askdirectory()
        window.destroy()
        window.mainloop()
        return directory
    
    def load_from_pickle(self):
        print('\n',horizontal_line)
        with open(self.file_path, 'rb') as file:
            print('loading data from pickle')
            loaded_data = pickle.load(file)
            print('Unpacking dataframe from pickle')
            try: 
                self.df = loaded_data['DataFrame']
            except KeyError:
                raise KeyError('Pickle does not contain dictionary key called DataFrame')
                
            print('Unpacking metadata dictionary from pickle')
            try:
                self.metadata_dict = loaded_data['Metadata_dict']
            except KeyError:
                print('Pickle does not contain dictionary key called Metadata_dict')
                
            print('Unpacking regress dictionary from pickle')
            try:
                self.regress_dict = loaded_data['Regress_dict']
            except KeyError:
                print('No regress dictionary in pickle')
                pass

                
            
    def export_to_pickle(self):
        # Exports just the df. It is possible to export the entire instance but I'm not sure how that would turn out. 
        # This way the instance re-initializes and the graphs are re-drawn.
        print('\n',horizontal_line)
        name = self.file_name
        name = name.replace('\\','/')
        directory = self.get_folder()
        directory = directory.replace('\\','/')
        file_path = os.path.join(directory, name + '.pkl')
        file_path = file_path.replace('\\', '/')
        with open(file_path, 'wb') as file:
            pickle.dump({'DataFrame':self.df,'Regress_dict':self.regress_dict,'Metadata_dict':self.metadata_dict}, file)
        print(f"DataFrame exported to {file_path}")

        
    def plot_dataframe(self,
                       x_lim=None,y_lim=None,
                       grid_y1_lines=1000,
                       subset_IV=1,subset_diameter_G=10, 
                       diameter_G_threshold=['median',1.5],
                       IV_linewidth=1, diameter_G_linewidth=0.5,
                       plot_V=True, plot_I=True,plot_diameter=False, plot_G=False
                      ):
        """
        diameter_threshold cuts off diameter values on plot outside of a certain value. 
            pass a list of the form [stat type, value] or False
            where stat type is 'median' for example and value is a number multiplier of that stat value to set the threshold limit to.
        """
        print('\n',horizontal_line)
        print('Plotting...')
        # Slice df to speed up ploting
        print('Slicing self.df by',subset_IV)
        subset_df = self.df.iloc[::subset_IV]
        print('Initializing fig, ax')
        self.fig, self.ax = plt.subplots(num=self.file_name,figsize=(10, 6))
        
        # Plot Current and Voltage vs Time in the same y-axis
        if plot_I == True:
            print('Plotting I-t curve')
            self.ax.plot(subset_df['Time'], subset_df['Current'], label='Current', linewidth=IV_linewidth)
        if plot_V == True:
            print('Plotting V-t curve')
            self.ax.plot(subset_df['Time'], subset_df['Voltage'], label='Voltage', linewidth=IV_linewidth)
        self.ax.set_xlabel('Time (s)')
        self.ax.set_ylabel('Current (pA), Voltage (mV)')
        threshold_value = False
        # See if there is G or diameter data, plot it if there is
        try:
            if plot_diameter == False and plot_G == False:
                skip_state = 'user_keyerror'
                raise KeyError()
            else:
                self.ax2 = self.ax.twinx()
            if plot_diameter == True:
                # Attempt to plot the diameter curve. 
                # If the Diameter column does not exist, a KeyError will be encountered with skip_state='diameter_keyerror'
                skip_state = 'diameter_keyerror'
                print('Slicing subset_df further by',subset_diameter_G,'to plot diameter')
                diameter_df = subset_df.iloc[::subset_diameter_G]
                if diameter_G_threshold == False:
                    print('No threshold applied to diameter curve')
                    pass
                elif len(diameter_G_threshold) == 2 and isinstance(diameter_G_threshold[0],str) and isinstance(diameter_G_threshold[1],numbers.Number):
                    print('Calculating diameter',diameter_G_threshold[0])
                    result = getattr(subset_df['Diameter'], diameter_G_threshold[0])()
                    threshold_value = abs(result - result*diameter_G_threshold[1])
                    print('Slicing diameter_df by threshold value')
                    diameter_df = diameter_df[abs(diameter_df['Diameter']-result) <= threshold_value]
                    self.ax2.hlines([result+threshold_value,result-threshold_value], xmin=0, xmax=self.time, color='green', linewidth=0.5,label='Diameter threshold value')
                else:
                    raise ValueError('Must be [str,number]')
                print('Plotting diameter curve')
                self.ax2.plot(diameter_df['Time'], diameter_df['Diameter'], label='Diameter', linewidth=diameter_G_linewidth,color='black')
                # Plot threshold values as well (not neccessary if removing diameter data at V=0)
                self.ax2.set_ylim(0,None)
                self.ax2.set_ylabel('Diameter (nm)')
            else:
                pass
            if plot_G == True:
                # Attempt to plot the G curve. 
                # If the Diameter column does not exist, a KeyError will be encountered with skip_state='G_keyerror'
                skip_state = 'G_keyerror'
                print('Slicing subset_df further by',subset_diameter_G,'to plot G')
                G_df = subset_df.iloc[::subset_diameter_G]
                if diameter_G_threshold == False:
                    print('No threshold applied to G curve')
                    pass
                elif len(diameter_G_threshold) == 2 and isinstance(diameter_G_threshold[0],str) and isinstance(diameter_G_threshold[1],numbers.Number):
                    result = getattr(subset_df['G'], diameter_G_threshold[0])()
                    threshold_value = result*diameter_G_threshold[1]
                    G_df = G_df[abs(G_df['G']) <= threshold_value]
                    self.ax2.hlines([threshold_value,-threshold_value], xmin=0, xmax=self.time, color='green', linewidth=0.5,label='G threshold value')
                else:
                    raise ValueError('Must be [str,number] or False')                
                self.ax2.plot(G_df['Time'], G_df['G'], label='G', linewidth=diameter_G_linewidth,color='red')
                # Plot threshold values as well
                self.ax2.set_ylim(0,None)
                self.ax2.set_ylabel('G (nS)')
            else:
                pass


            
            # Combine legends for both ax1 and ax2
            handles1, labels1 = self.ax.get_legend_handles_labels()
            handles2, labels2 = self.ax2.get_legend_handles_labels()
            handles = handles1 + handles2
            labels = labels1 + labels2
            self.ax.legend(handles, labels, loc='upper left')
        except KeyError:
            if skip_state == 'user_keyerror':
                print('Skipping diameter and G plots')
            elif skip_state == 'diameter_keyerror':
                print('No diameter column')
            elif skip_state == 'G_keyerror':
                print('No G column')
           
        self.ax.set_xlim(x_lim)
        self.ax.set_ylim(y_lim)
        self.ax.set_title(self.file_name,size=10)
        #self.ax.legend() 
        # Calculate grid spacing based on a factor of the range of the y-axis
        y_range = subset_df['Current'].max() - subset_df['Current'].min()
        if (y_range/grid_y1_lines) >= 1000:
                raise ValueError('grid_y1_lines too small, producing more than 1000 grid lines in the y axis')
        # For some reason grid_y1_lines = 1 results in 10 grid lines. Divide user input by 10
        #grid_y1_lines = grid_y1_lines / 10
        #grid_spacing = y_range / grid_y1_lines
        # Use absolute values of grid lines input rather than a regular spacing
        self.ax.yaxis.set_major_locator(plt.MultipleLocator(grid_y1_lines))
        self.ax.grid(True, linestyle='--', linewidth=0.5, color='gray', alpha=0.7)
        #self.ax.grid(True)
        #plt.tight_layout()
        plt.show()

        
        if threshold_value:
            print(diameter_G_threshold[0],':',result)
            print('Threshold values relative to the',diameter_G_threshold[0],'+/-',threshold_value)
            print('Absolute threshold values:',result-threshold_value,'-',result+threshold_value)
            return threshold_value
        else:
            return 



    
    def plot_regress_on_existing_plot(self,a=0,b=1,x_name='Time',y_name='Current',name='default',existing_regress=None):
        """
        name can be string entry for dictionary. Default: filename_a-b.
        self.regress is a dictionary containing regress plots
        existing_regress take a scipy.stats linear regression object ie: [instance_name].regress[0]
        if existing_regress is entered, the function will return the same scipy.stats linear regression object, for symmetry
        """
        #if name == 'default':
        #    name=str(self.name+'___'+str(a)+'-'+str(b))
        #else:
        #    name = name
        if existing_regress == None:
            start_time = time.time()
            a=a
            b=b
            slice_df = self.df[(self.df[x_name] >= a) & (self.df[x_name] <= b)]
            x=slice_df[x_name]
            y=slice_df[y_name]

            linear_regression = scipy.stats.linregress(x=x,y=y)
            regname = str(str(a)+'_'+str(b)+'_'+y_name)
            self.regress_dict[regname] = [linear_regression,a,b,y_name]
            slope = linear_regression.slope
            intercept = linear_regression.intercept
            self.linreg = linear_regression
            print(linear_regression)
            end_time = time.time()
            elapsed_time = end_time - start_time
            print('Time elapsed during regression')
            x_range = np.linspace(a, b, 100)
            y_range = slope * x_range + intercept
            if y_name == 'Current':
                plt.sca(self.ax)
            elif y_name == 'Diameter':
                plt.sca(self.ax2)
            axreg = self.fig.gca()
            axreg.plot(x_range, y_range, color='r', linewidth=1.5)
            
            #self.regress_count += 1

            return linear_regression, self.fig
        else:
            slope = existing_regress[0].slope
            intercept = existing_regress[0].intercept
            print(slope,intercept)
            a=existing_regress[1]
            b=existing_regress[2]
            y_name=existing_regress[3]
            if y_name == 'Current':
                plt.sca(self.ax)
            elif y_name == 'Diameter':
                plt.sca(self.ax2)
            x_range = np.linspace(a, b, 100)
            y_range = slope * x_range + intercept
            axreg = self.fig.gca()
            axreg.plot(x_range, y_range, color='r', linewidth=1.5)
            return existing_regress, self.fig
        
    def plot_regress_dict(self):
        for existing_regress in self.regress_dict:
            slope = self.regress_dict[existing_regress][0].slope
            intercept = self.regress_dict[existing_regress][0].intercept
            print(existing_regress,'slope:',slope,'intercept:',intercept)
            a=self.regress_dict[existing_regress][1]
            b=self.regress_dict[existing_regress][2]
            y_name=self.regress_dict[existing_regress][3]
            if y_name == 'Current':
                plt.sca(self.ax)
            elif y_name == 'Diameter':
                plt.sca(self.ax2)
            x_range = np.linspace(a, b, 100)
            y_range = slope * x_range + intercept
            axreg = self.fig.gca()
            axreg.plot(x_range, y_range, color='r', linewidth=1.5)
            self.fig
        return existing_regress, self.fig
    def save_current_plot(self,image_name = 'default'):
        if image_name == 'default':
            image_name = self.file_name
        else:
            pass
        directory = self.get_folder()
        filepath = directory + image_name + '.png'
        print(filepath)
        self.fig.savefig(filepath)
        
        