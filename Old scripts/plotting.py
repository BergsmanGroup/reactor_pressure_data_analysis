import matplotlib.pyplot as plt
import numpy as np
import os
#from moviepy.editor import ImageSequenceClip
import glob
import imageio.v2 as imageio
import re
import sys
from matplotlib.ticker import MultipleLocator
import pandas as pd



#    def plot_cycles(self, cycles='all', title='default', xlim=[None, None], ylim=[None, None], retfig=True, showfig=False):
#        if cycles == 'all':
#            num = int(self.df['cycle'].max()) + 1
##            for i in range(1, num):
#                print(f'Cycle {i}')
#                current_title = f'{self.sourceinfo_dict["file_name"]} cycle {i}' if title == 'default' else title
#                df_cycle = self.df[self.df['cycle'] == i]
#                fig = plotting.plot_cycle(df_cycle, current_title, xlim, ylim, retfig, showfig)
#                self.fig_dict[f"{i}"] = fig
#        else:
#            for i in cycles:
#                title = f'{self.sourceinfo_dict["file_name"]} cycle {i}' if title == 'default' else title
#                df_cycle = self.df[self.df['cycle'] == i]
#                fig = plotting.plot_cycle(df_cycle, title, xlim, ylim, retfig, showfig)
#                self.fig_dict[f"{i}"] = fig

def numerical_sort(value):
    """
    Sort function that handles filenames with numbers correctly.
    """
    numbers = re.findall(r'\d+', value)
    return list(map(int, numbers)) if numbers else [value]


def plot_cycle(cycledf, title, xlim, ylim, retfig, showfig):
    fig, ax = plt.subplots(figsize=(10,8))

    # Plot each phase with a unique color
    for phase, color in zip(cycledf['phase'].unique(), plt.cm.tab10(np.linspace(0, 1, cycledf['phase'].nunique()))):
        df_phase = cycledf[cycledf['phase'] == phase]
        ax.plot(df_phase['cycle_time'], df_phase['pressure'], linestyle='-', color=color, label=phase)

    # Set axis labels
    ax.set_xlabel('Time')
    ax.set_ylabel('Pressure')

    # Grid and axis limits
    ax.grid(True)
    ax.set_xlim(xlim[0], xlim[1])
    ax.set_ylim(ylim[0], ylim[1])

    # Add legend outside plot area
    ax.legend(loc='center left', bbox_to_anchor=(1, 0.5))

    # Set title directly on the axes
    ax.set_title(title, fontsize=14)

    # Automatically adjust layout to fit everything
    plt.tight_layout()
    #plt.subplots_adjust(left=0.2)

    if showfig:
        plt.show()
    if retfig:
        plt.close(fig)
        return fig

    return None


def static_cycles(cycles, filename, df, xlim, ylim, title='default', retfig=False, showfig=True):
    fig_dict = {}
    total_cycles = len(cycles)
    
    for idx, i in enumerate(cycles):
        if title == 'default':
            figure_title = f'{filename} cycle {i}'
        else:
            figure_title = f'{title} cycle {i}'
        df_cycle = df[df['cycle'] == i]
        fig = plot_cycle(df_cycle, figure_title, xlim, ylim, retfig, showfig)
        if retfig:
            fig_dict[f'{i}'] = fig
        
        # Update progress on the same line
        progress = (idx + 1) / total_cycles * 100
        sys.stdout.write(f'\rProcessing cycle ({idx + 1}/{total_cycles})')
        sys.stdout.flush()
    
    print()  # Print a newline after finishing

    if retfig:
        return fig_dict




def generate_animation(figdict, targetdirectory,spf):
    # Create the directory if it doesn't exist
    os.makedirs(targetdirectory, exist_ok=True)
    frames = len(figdict)
    fps = 1/spf
    # Save each figure to the specified directory
    print(f"Saving images to directory: {targetdirectory}")
    for name, fig in figdict.items():
        fig_path = os.path.join(targetdirectory, f'{name}.png')
        fig.savefig(fig_path, dpi=72)  # Lower DPI for faster processing
        print(f"Saved figure: {fig_path}")
        plt.close(fig)  # Close the figure to free up memory
    
    # Get a list of image file paths
    image_files = glob.glob(glob.escape(targetdirectory) + '/*.png')
    print("Image files found:", image_files)
    
    # Sort the image files using the numerical_sort function
    image_files.sort(key=numerical_sort)
    
    # Check if any images were found
    if not image_files:
        print("No images found. Cannot create animation.")
        return
    
    # Use imageio to create a GIF with infinite looping
    print('Generating animation...')
    images = [imageio.imread(img) for img in image_files]
    animation_path = os.path.join(targetdirectory, 'animation.gif')
    imageio.mimsave(animation_path, images, fps=fps, loop=0)
    
    print(f'Animation saved to {animation_path}')

def plot_integrated_barchart(df, ylim,title):
    bar_width = 0.35
    # Convert cycles to numeric np array
    cycles = pd.to_numeric(df['cycle'], errors='coerce').unique()
    valves = df['valve'].unique()
    fig, ax = plt.subplots(figsize=(10, 5))
    
    # Plotting the bars
    for i, valve in enumerate(valves):
        valve_data = df[df['valve'] == valve]['integral']
        ax.bar(cycles + i * bar_width, valve_data, bar_width, label=valve)

    # Add labels and title with customized font size
    ax.set_ylim(ylim)
    ax.set_xlabel('Cycle', fontsize=10)
    ax.set_ylabel('Integral of dose + hold', fontsize=10)
    ax.set_title(title, fontsize=10)
    ax.tick_params(axis='both', which='major', labelsize=10)
    ax.xaxis.set_major_locator(MultipleLocator(10))
    
    # Add legend
    ax.legend(fontsize=10)
    
    # Display the chart
    plt.tight_layout()
    return fig