# The timing rows, loaded from the recipe sheet workbook, are correct
Timing rows:
Cycles  Valve #  Pre-dose Pump (s)  N2 Dose (s)  Pump Dose (s)  Dose (s)  Hold (s)  Pre-Purge (s)  Purge (s)  Sequence Notes
     1        7                  0           15              0         0         0              0         10
     1        5                  4          0.5              0         0         0              0        300
              8                  4          0.5              0         0         0              0        300
              8                  4            0              0         0        60              0         10
              7                  0           15              0         0         0              0         10
     1        5                  4            0              0       300        60              0        600
              5                  4            0              0         0        60              0         10
              8                  4            0              0       300        60              0        600
              8                  4            0              0         0        60              0         10
              7                  0           15              0         0         0              0         10
     1        5                  4            0              0       300        60              0        300
              5                  4            0              0         0        60              0         10
              8                  4            0              0       300        60              0        300
              8                  4            0              0         0        60              0         10
              7                  0           15              0         0         0              0         10




# The full phase bins this should produce are shown below. I have not removed any redundant numbers. 
[0, 0, 15, 15, 15, 15, 15, 25] 
[0, 4, 4.5, 4.5, 4.5, 4.5, 4.5, 304.5, 308.5, 309, 309, 309, 309, 309, 609, 613, 613, 613, 613, 673, 673, 683, 683, 698, 698, 698, 698, 698, 708]
[0, 4, 4, 4, 304, 364, 364, 964, 968, 968, 968, 968, 1028, 1028, 1038, 1042, 1042, 1042, 1342, 1402, 1402, 2002, 2006, 2006, 2006, 2006, 2066, 2066, 2076]
[0, 4, 4, 4, 304, 364, 364, 664, 668, 668, 668, 668, 728, 728, 738, 742, 742, 742, 1042, 1102, 1102, 1402, 1406, 1406, 1406, 1406, 1466, 1466, 1476]


# The anticipated phase bins calculated before payload generation are incorrect. 
Anticipated phase bins (shift = 2.0 s):
  seq1 bins (s): [0.0, 17.0, 29.0]
  seq1 phases  : ['seq1_GV_dosepump', 'seq1_GV_purge']
  seq2 bins (s): [0.0, 6.0, 8.5, 310.5, 316.5, 378.5, 390.5, 407.5, 419.5]
  seq2 phases  : ['seq2_TDIC_prepump', 'seq2_TDIC_dosepump', 'seq2_TDIC_purge', 'seq2_DAMDPA_prepump', 'seq2_DAMDPA_hold', 'seq2_DAMDPA_purge', 'seq2_GV_dosepump', 'seq2_GV_purge']
  seq3 bins (s): [0.0, 6.0, 68.0, 80.0, 86.0, 148.0, 160.0, 177.0, 189.0]
  seq3 phases  : ['seq3_TDIC_prepump', 'seq3_TDIC_hold', 'seq3_TDIC_purge', 'seq3_DAMDPA_prepump', 'seq3_DAMDPA_hold', 'seq3_DAMDPA_purge', 'seq3_GV_dosepump', 'seq3_GV_purge']
  seq4 bins (s): [0.0, 6.0, 68.0, 80.0, 86.0, 148.0, 160.0, 177.0, 189.0]
  seq4 phases  : ['seq4_TDIC_prepump', 'seq4_TDIC_hold', 'seq4_TDIC_purge', 'seq4_DAMDPA_prepump', 'seq4_DAMDPA_hold', 'seq4_DAMDPA_purge', 'seq4_GV_dosepump', 'seq4_GV_purge']


# The output of loading the header and processing the raw data is incorrect. In the raw data file has been edited so that the N2Dose column of the valve sequence in sequence 2 has 0.5 and 0.5 for valve5 and valve8, but the loaded header only has 0.5 and 0. 
Loading:  C:/Users/Owner/OneDrive - UW/Documents - bergsmangroup/Data/Reactor Data/JSON Files/260819_22h07m__InSituReactorJay_EDRTrue_DID141_Chamber100_GV60_TDIC35_DAMDPA30_Reactor1_Data.json
Timing table:
  seq1 (cycles: 1)
    valve7: [0, 15, 0, 0, 0, 0, 10]
  seq2 (cycles: 1)
    valve5: [4, 0.5, 0, 0, 0, 0, 300]
    valve8: [4, 0, 0, 0, 60, 0, 10]
    valve7: [0, 15, 0, 0, 0, 0, 10]
  seq3 (cycles: 1)
    valve5: [4, 0, 0, 0, 60, 0, 10]
    valve8: [4, 0, 0, 0, 60, 0, 10]
    valve7: [0, 15, 0, 0, 0, 0, 10]
  seq4 (cycles: 1)
    valve5: [4, 0, 0, 0, 60, 0, 10]
    valve8: [4, 0, 0, 0, 60, 0, 10]
    valve7: [0, 15, 0, 0, 0, 0, 10]
  seq1: 1 cycles -- valve7
  seq2: 1 cycles -- valve5, valve8, valve7
  seq3: 1 cycles -- valve5, valve8, valve7
  seq4: 1 cycles -- valve5, valve8, valve7
Details:
{
  "Info": "Do dose testing of freshly heated precursors before starting run. Start with N2Dose to clear the headspace and then do \"standard\" 300 s dose with a 60s hold just to see if the pressure drops, followed by decreasing purge times each sequence",
  "WaitTime": 0,
  "EDR": true,
  "DID": [141],
  "ValvePrecursor": ["nan", 7, 5, 8, 6, 12],
  "Name": ["Chamber", "GV", "TDIC", "DAMDPA", "MeI", "LeakRate"],
  "TempC": [100, 60, 35, 30, 25, "nan"],
  "ProcessTimeHr": 1.204167,
  "EndTime": "2026-08-19 23:19:27",
  "SID": [],
  "EID": [],
  "PID": []
}
Loaded:  Jay_EDRTrue_DID141_Chamber100_GV60_TDIC35_DAMDPA30

-- 260819_22h07m__InSituReactorJay_EDRTrue_DID141_Chamber100_GV60_TDIC35_DAMDPA30_Reactor1_Data.json
  seq1 bins (s): [0.0, 17.0, 29.0]
  seq1 phases  : ['seq1_GV_dosepump', 'seq1_GV_purge']
  seq2 bins (s): [0.0, 6.0, 8.5, 310.5, 316.5, 378.5, 390.5, 407.5, 419.5]
  seq2 phases  : ['seq2_TDIC_prepump', 'seq2_TDIC_dosepump', 'seq2_TDIC_purge', 'seq2_DAMDPA_prepump', 'seq2_DAMDPA_hold', 'seq2_DAMDPA_purge', 'seq2_GV_dosepump', 'seq2_GV_purge']
  seq3 bins (s): [0.0, 6.0, 68.0, 80.0, 86.0, 148.0, 160.0, 177.0, 189.0]
  seq3 phases  : ['seq3_TDIC_prepump', 'seq3_TDIC_hold', 'seq3_TDIC_purge', 'seq3_DAMDPA_prepump', 'seq3_DAMDPA_hold', 'seq3_DAMDPA_purge', 'seq3_GV_dosepump', 'seq3_GV_purge']
  seq4 bins (s): [0.0, 6.0, 68.0, 80.0, 86.0, 148.0, 160.0, 177.0, 189.0]
  seq4 phases  : ['seq4_TDIC_prepump', 'seq4_TDIC_hold', 'seq4_TDIC_purge', 'seq4_DAMDPA_prepump', 'seq4_DAMDPA_hold', 'seq4_DAMDPA_purge', 'seq4_GV_dosepump', 'seq4_GV_purge']
Reading data...
  4 cycles, 43,759 pressure points
Writing condensed log...
  Baseline subtracted: 218.10 mTorr
Generating plots...

Done -- 4 plots saved to:
  C:\Users\Owner\OneDrive - UW\Documents - bergsmangroup\Data\Reactor Data\JSON Files\cycle_plots_260819_22h07m
  Raw rows before condense: 217,942 total, 43,763 pressure
  File size: 35.72 MB -> 8.51 MB (76.2% reduction)
  Condensed: 260819_22h07m__InSituReactorJay_EDRTrue_DID141_Chamber100_GV60_TDIC35_DAMDPA30_Reactor1_Data_condensed.json  (43,763 data rows)
Computing phase exposures...
  Exposure CSV: 260819_22h07m__InSituReactorJay_EDRTrue_DID141_Chamber100_GV60_TDIC35_DAMDPA30_Reactor1_Data_exposure.csv  (3 rows)
  Thickness CSV: skipped (select a valid iSE data file)









