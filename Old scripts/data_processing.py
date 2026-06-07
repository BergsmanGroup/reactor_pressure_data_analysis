import pandas as pd
import json
import warnings
import re
import numpy as np
import io

# Reuse your converter so detection+conversion stays in one place
# (assumes new_to_old_jsonlog.py is in the same directory / on the PYTHONPATH)
from new_to_old_jsonlog import convert_stream, DROP_TYPES, DROP_PAYLOAD_KEYS  # :contentReference[oaicite:1]{index=1}

def _looks_like_new_format(lines):
    """
    Heuristics to detect the 'new' NDJSON log format so we can convert on the fly:
      - record type is in DROP_TYPES (e.g., step/currentstep)
      - payload is a JSON-encoded string (starts with '{' or '[')
      - payload dict contains any key in DROP_PAYLOAD_KEYS (e.g., CurrentStep)
    """
    for line in lines[:2000]:  # sample the first couple thousand lines safely
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue

        rtype = str(rec.get("type", "")).lower()
        if rtype in DROP_TYPES:
            return True

        payload = rec.get("payload", None)

        # JSON-string payload (common in the new format)
        if isinstance(payload, str):
            s = payload.strip()
            if s and (s[0] in "{[" and s[-1] in "}]"):
                return True

        # New-only payload keys present
        if isinstance(payload, dict) and any(k in payload for k in DROP_PAYLOAD_KEYS):
            return True

    return False

def _maybe_convert_new_to_old(lines):
    """
    If the input looks like the new format, run it through the in-memory converter
    and return converted NDJSON lines. Otherwise, return original lines.
    """
    if not _looks_like_new_format(lines):
        return lines

    instream = io.StringIO("".join(lines))
    outstream = io.StringIO()
    convert_stream(instream, outstream)  # uses your rules to drop/strip new-only fields
    outstream.seek(0)
    return outstream.read().splitlines(True)

def load_reactor_json(file_path):
    with open(file_path, 'r', encoding='utf-8') as file:
        orig_lines = file.readlines()

    # Convert on-the-fly if needed so downstream parsing stays identical
    lines = _maybe_convert_new_to_old(orig_lines)

    # Proceed as before on "old" format lines
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
            warnings_dict[f"Header key {key}"] = f"{key} is missing or empty in header payload"

    guid_pattern = re.compile(r'^\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}$')
    if not guid_pattern.match(payload.get('GUID', '')):
        warnings.warn("header GUID format is incorrect")
        warnings_dict['Header GUID'] = 'Header GUID format is incorrect'

    print("Header and footer validation complete.")
    return warnings_dict

def generate_sequencedetail_columns(df, valveSeq):
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

def cut_by_phases(df, valveSeq, shift):
    print(f"Shift applied:{shift}s")
    def generate_compact_sequence_dict(valveSeq):
        seq_compactdict = {}
        for i in range(1, len(valveSeq) + 1):
            sequence_compactlist = []
            cycles = [valveSeq[f"seq{i}"]['cycles']]
            for entry in valveSeq[f"seq{i}"]:
                if entry.startswith('valve'):
                    sequence_compactlist.extend(valveSeq[f"seq{i}"][entry])
            seq_compactdict[f"seq{i}"] = sequence_compactlist
        return seq_compactdict

    def phasenames(sequence_valveSeq, sequence):
        phase_types = ['prepump', 'dosepump', 'dosen2', 'dose', 'hold', 'prepurge', 'purge']
        sequence_phasenames = []
        for key in sequence_valveSeq:
            if key == 'cycles':
                continue
            i = 0
            key_phasenames = []
            for value in sequence_valveSeq[key]:
                key_phasenames.append(f"{sequence}_{key}_{phase_types[i]}")
                i += 1
            sequence_phasenames.extend(key_phasenames)
        return sequence_phasenames

    compactdict = generate_compact_sequence_dict(valveSeq)
    for seq in compactdict:
        compact_sequence_list = compactdict[seq]
        num_components = int(len(compact_sequence_list) / 7)
        sequence_phasenames = phasenames(valveSeq[seq], seq)
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
                if i < len(sequence_phasenames):
                    phase_names.append(sequence_phasenames[i])
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

    df = df.groupby('sequence', group_keys=False).apply(assign_phase_to_group).reset_index(drop=True)
    print('Finished cutting data by phases')
    return df, valveSeq

def total_expected_cycles(valveSequence):
    total = 0
    for seq_key, seq_data in valveSequence.items():
        total += seq_data.get('cycles', 0)
    return total

def prompt_change_key(result):
    # Collect all unique 'valve' keys with numbers
    keys_to_change = set()
    for seq, data in result.items():
        for key in data.keys():
            if key.startswith("valve") and re.search(r'\d+', key):
                keys_to_change.add(key)

    # Prompt the user to change the numeric part of each unique key
    key_mapping = {}
    for key in keys_to_change:
        number_part = re.search(r'\d+', key).group()
        new_part = input(f"The key '{key}' starts with 'valve' and ends with number '{number_part}'. Enter a new string to replace this number (leave blank to keep the original): ")
        if new_part:  # Only update if new_part is not empty
            new_key = re.sub(r'\d+', new_part, key)
            key_mapping[key] = new_key

    # Update the dictionary with the new keys
    for seq, data in result.items():
        for key, value in list(data.items()):
            if key in key_mapping:
                data[key_mapping[key]] = value
                del data[key]

    return result

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
                current_sequence[f"valve{valvenum}"] = sublist[2:]
            else:  # If it does not start with 0, it's a new sequence
                if current_sequence:
                    result[f"seq{seq_count}"] = current_sequence
                    seq_count += 1
                current_sequence = {
                    'cycles': cyclecount,
                    f"valve{valvenum}": sublist[2:]
                }

        else:
            # Ignore lists that only contain zeros
            continue

    # Add the last sequence
    if current_sequence:
        result[f"seq{seq_count}"] = current_sequence
    print('Finished converting valveSequence to dictionary')

    return result

def calculate_integral(df):
    # Initialize a dictionary to store results
    new_df = pd.DataFrame(columns=['cycle', 'sequence', 'sequence_cycle', 'valve', 'integral'])
    # Loop over each unique cycle
    for cycle in df['cycle'].unique():
        cycle_data = df[df['cycle'] == cycle].dropna()
        for phase in cycle_data['phase'].unique():
            phase_name = str(phase).split(sep='_')[2]

            if phase_name in ['dose', 'hold']:
                phase_data = cycle_data[cycle_data['phase'] == phase]
                time = phase_data['time'].values
                pressure = phase_data['pressure'].values

                # Calculate the integral using the trapezoidal rule
                integral = np.trapezoid(pressure, time)
                sequence = phase_data.iloc[0]['sequence']
                sequence_cycle = f"seqCycle{phase_data.iloc[0]['sequence_cycle']}"
                integral = round(integral)
                valve = str(phase_data.iloc[0]['phase']).split(sep='_')[1]
                df_row = pd.DataFrame([[cycle, sequence, sequence_cycle, valve, integral]],
                                      columns=['cycle', 'sequence', 'sequence_cycle', 'valve', 'integral'])
                new_df = pd.concat([new_df, df_row], ignore_index=True)
    df_grouped = new_df.groupby(['cycle', 'valve', 'sequence', 'sequence_cycle'], as_index=False).agg({'integral': 'sum'})
    df_pivot = df_grouped.pivot_table(index=['cycle', 'sequence', 'sequence_cycle'],
                                      columns='valve',
                                      values='integral').reset_index()
    return df_pivot
