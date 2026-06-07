import easygui
import os
def sourceinfo_easygui():
    # Allow selection of both .json and .pkl files
    file_path = easygui.fileopenbox(title="Select a File", default='*', filetypes=["JSON and PKL files", "*.json;*.pkl"])
    print(file_path)
    
    if file_path:
        source_info = split_pathinfo(file_path)
        print(source_info)
        return source_info
    else:
        return None

def sourceinfo_abspath(abspath):
	file_path = abspath
	source_info = split_pathinfo(file_path)
	return source_info

def split_pathinfo(file_path):
	source_info = {}
	source_info['file_path'] = file_path
	file_name_withext, source_info['file_ext'] = os.path.splitext(file_path)
	source_info['file_directory'] = os.path.dirname(file_path)
	source_info['file_name'] = os.path.basename(file_name_withext)
	source_info['pickle_name'] = f"{source_info['file_name']}.pkl"
	return source_info

def file_explorer():
	file_path = easygui.fileopenbox(title="Select a File",default='*.json', filetypes=['*.pkl','*.json'])
	print(f"Filepath {file_path}")
	return file_path

def directory_explorer():
	directory = easygui.diropenbox(title="Select a Directory")
	print(f"Directory {directory}")
	return directory


