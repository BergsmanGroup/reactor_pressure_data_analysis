import pandas as pd
import json
import warnings
import re








def load_reactor_json(file_path):
    with open(file_path, 'r') as file:
        lines = file.readlines()
        data = [json.loads(line) for line in lines]

    header = data[0]
    footer = data[-1]
    trimmed = data[1:-1]

    time, pressure, cycle = [], [], []
    batch_size = 1000

    for i in range(0, len(trimmed), batch_size):
        for j in range(i, min(i + batch_size, len(trimmed))):
            try:
                if trimmed[j]['payload']['Pressure'] != '':
                    time.append(float(trimmed[j]['payload']['TimeElapsed']) / 1000)
                    pressure.append(trimmed[j]['payload']['Pressure'])
                    cycle.append(trimmed[j]['payload']['CurrentCycle'])
            except KeyError as e:
                print(f"Error processing record {j}: {e}")

    df = pd.DataFrame({
        'time': time,
        'pressure': pressure,
        'cycle': cycle
    })
    print('Finished loading data from json')
    return df, header, footer

def check_header_footer(header, footer):
    warnings_dict = {}

    if header['type'] != 'header':
        warnings.warn("Header type is not 'header'")
        warnings_dict['Header'] = "Header type is not 'header'"

    if header['meta'] != '':
        warnings.warn("Header meta is not an empty string")
        warnings_dict['Meta'] = "Header meta is not an empty string"

    required_keys = ['GUID', 'username', 'experimentalDetails', 'valveSequence', 'startTime', 'reactorName']
    payload = header.get('payload', {})

    for key in required_keys:
        if key not in payload or not payload[key]:
            warnings.warn(f"{key} is missing or empty in header payload")
            warnings_dict[f'Header key {key}'] = f"{key} is missing or empty in header payload"

    guid_pattern = re.compile(r'^\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}$')
    if not guid_pattern.match(payload.get('GUID', '')):
        warnings.warn("header GUID format is incorrect")
        warnings_dict['Header GUID'] = 'Header GUID format is incorrect'

    # Validate footer similarly...

    print("Header and footer validation complete.")
    return warnings_dict


def generate_sequencedetail_columns(df,valveSeq):
    # Create a mapping of cycle to sequence and sequence cycle count
    cycle_to_sequence = {}
    sequence_cycle_count = {}
    cycle_count = 1
    for seq, details in valveSeq.items():
        for cycle in range(1, details['cycles'] + 1):
            cycle_to_sequence[cycle_count] = seq
            sequence_cycle_count[cycle_count] = cycle
            cycle_count += 1

    # Function to map cycle to sequence
    def map_cycle_to_sequence(cycle):
        return cycle_to_sequence.get(cycle, 'unknown')

    # Function to map cycle to sequence cycle
    def map_cycle_to_sequence_cycle(cycle):
        return sequence_cycle_count.get(cycle, 0)

    # Apply the functions to create new columns
    df['sequence'] = df['cycle'].apply(map_cycle_to_sequence)
    df['sequence_cycle'] = df['cycle'].apply(map_cycle_to_sequence_cycle)
    df['cycle_time'] = df.groupby('cycle')['time'].transform(lambda x: x - x.min())
    print('Finished generating sequence detail columns')
    return df


def cut_by_phases(df, valveSeq,shift):
    print(f'Shift applied:{shift}s')
    def generate_compact_sequence_dict(valveSeq):
        seq_compactdict = {}
        for i in range(1,len(valveSeq)+1):
            sequence_compactlist = []
            cycles = [valveSeq[f'seq{i}']['cycles']]
            for entry in valveSeq[f'seq{i}']:
                if entry.startswith('valve'):
                    sequence_compactlist.extend(valveSeq[f'seq{i}'][entry])
            seq_compactdict[f'seq{i}'] = sequence_compactlist
        return seq_compactdict
    compactdict = generate_compact_sequence_dict(valveSeq)
    for seq in compactdict:
        compact_sequence_list = compactdict[seq]
        num_components = int(len(compact_sequence_list)/7)
        phase_types = ['prepump', 'dosepump', 'dosen2', 'dose', 'hold', 'prepurge', 'purge']
        phase_names_all = [f'{seq}_{phase}_{i}' for i in range(1, num_components + 1) for phase in phase_types]
        i = 0
        summy = 0
        phase_bins = [0]
        phase_names = []
        for value in compact_sequence_list:
            if value == 0:
                i += 1
                pass
            elif value != 0:
                summy = summy + value + shift
                phase_bins.append(summy)
                if i < len(phase_names_all):
                    phase_names.append(phase_names_all[i])
                    i += 1
        valveSeq[seq]['phase_bins'] = phase_bins
        valveSeq[seq]['phase_names'] = phase_names
    def assign_phase_to_group(group):
        seq = group.name  # Get the sequence value for this group
        if seq == 'unknown':
            return
        bins = valveSeq[seq]['phase_bins']
        labels = valveSeq[seq]['phase_names']
        group['phase'] = pd.cut(group['cycle_time'], bins=bins, labels=labels, right=False)
        return group

    df = df.groupby('sequence',group_keys=False).apply(assign_phase_to_group).reset_index(drop=True)
    print('Finished cutting data by phases')
    return df, valveSeq


def total_expected_cycles(valveSequence):
    total = 0
    for seq_key, seq_data in valveSequence.items():
        total += seq_data.get('cycles',0)
    return total


def convert_sequence(vaveSequence):
    result = {}
    seq_count = 1
    current_sequence = {}
    letter_index = 0  # Initialize the letter index

    def get_next_letter(reset=False):
        nonlocal letter_index
        if reset:
            letter_index = 0  # Reset the index
        letter = chr(ord('A') + letter_index)
        letter_index += 1
        return letter

    for sublist in vaveSequence:
        if any(sublist):  # Check if there's at least one non-zero element
            cyclecount = int(sublist[0])
            valvenum = int(sublist[1])
            if cyclecount == 0:  # If it starts with 0, it's part of the current sequence as 'B', 'C', etc.
                current_sequence[f'valve{valvenum}'] = sublist[2:]
            else:  # If it does not start with 0, it's a new sequence 
                if current_sequence:
                    result[f'seq{seq_count}'] = current_sequence
                    seq_count += 1
                current_sequence = {
                    'cycles': cyclecount,
                    f'valve{valvenum}':sublist[2:]
                }

        else:
            # Ignore lists that only contain zeros
            continue

    # Add the last sequence
    if current_sequence:
        result[f'seq{seq_count}'] = current_sequence
    print('Finished converting valveSequence to dictionary')
    
    return result