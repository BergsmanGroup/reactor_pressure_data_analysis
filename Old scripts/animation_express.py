import reactordata
import sys
import os
import json
script_dir = os.path.dirname(os.path.abspath(__file__))

# First argument is the absolute path to the JSON file
abspath = sys.argv[1]
title = sys.argv[2]
spf = float(sys.argv[3])
xlim = sys.argv[4]
ylim = sys.argv[5]


# Load the valve dictionary from the JSON file
with open(os.path.join(script_dir,'valvename.json'), 'r') as f:
    valve_dict = json.load(f)


# Rest of your script...
data = reactordata.ReactorData(abspath=abspath, valve_dict=valve_dict)
cycle_list = list(range(1, data.df['cycle'].max() + 1))
# Default behavior: use max of cycle x for x lim
#data.plot_static(cycles=cycle_list, filename=data.sourceinfo_dict['file_name'], df=data.df,
#                 title=title, retfig=True, showfig=False,
#                 xlim=[0, data.header['payload']['totals']['xlim']],
#                 ylim=[0, data.header['payload']['totals']['ylim']])
if xlim == 'default':
    xlim = [0, data.header['payload']['totals']['xlim']]
else:
    xlim = float(xlim)
    xlim = [0,xlim]

if ylim == 'default':
    ylim = [0, data.header['payload']['totals']['ylim']]
else:
    ylim = float(ylim)
    ylim = [0,ylim]
data.plot_static(cycles=cycle_list, filename=data.sourceinfo_dict['file_name'], df=data.df,
                 title=title, retfig=True, showfig=False,
                 xlim=xlim,
                 ylim=ylim)
savename = os.path.split(abspath)[1]
data.generate_animation(spf=spf)