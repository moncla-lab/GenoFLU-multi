import genoflu as gf
import os
from glob import glob
import pandas as pd
from Bio import SeqIO
import shutil
import argparse

if __name__ == '__main__':
    # get path/to/GenoFLU/bin
    # need this for default paths to reference directory and genotype key
    script_path = os.path.dirname(os.path.realpath(__file__))

    parser = argparse.ArgumentParser()

    parser.add_argument('-f', '--fasta_dir', action='store',
                        dest='fasta_dir', required=True, help='Assembled FASTA')
    parser.add_argument('-r', '--reference_dir', action='store', dest='reference_dir', default=os.path.join(script_path, '../dependencies/fastas'),
                        help='Directory containing FASTAs to BLAST against.  Headers must follow specific format.  genoflu/dependencies/fastas')
    parser.add_argument('-c', '--cross_reference', action='store', dest='cross_reference', default=os.path.join(script_path, '../dependencies/genotype_key.xlsx'),
                        help='Excel file to cross-reference BLAST findings and identification to genotyping results.  Default genoflu/dependencies.  9 column Excel file, first column Genotype, followed by 8 columns for each segment and what those calls are for that genotype.')

    args = parser.parse_args()

    # get paths to new directories and files to be generated
    temp_dir = os.path.join(args.fasta_dir, 'temp')
    temp_fasta = os.path.join(temp_dir, 'temp.fasta')
    results_dir = os.path.join(args.fasta_dir, 'results')
    results_tsv = os.path.join(results_dir, 'results.tsv')

    # if the temporary directory doesn't already exist, make it
    if not os.path.exists(temp_dir):
        os.makedirs(temp_dir)

    # and the results directory
    if not os.path.exists(results_dir):
        os.makedirs(results_dir)

    # if the results.tsv file already exists, pull out all annotated strains
    # this will prevent re-annotating strains that were previously annotated
    # (i.e., can add new sequences to your fastas and annotate only those)
    if os.path.exists(results_tsv):
        annotated_strains = list(pd.read_csv(results_tsv, sep='\t')['Strain'])
    else:
        annotated_strains = []

    # get list of all fastas within
    fastas = list(glob(os.path.join(args.fasta_dir, '*.fasta')))

    # make the blast db in a new 'blast' folder within the ../dependencies/fastas directory
    blast_dir = os.path.join(args.reference_dir, 'blast')
    blast_db = os.path.join(blast_dir, 'hpai_geno_db')

    # if blast directory already exists, delete it and all files inside
    # this will ensure if reference dataset is updated, so is the blast db
    if os.path.exists(blast_dir):
        shutil.rmtree(blast_dir)
    # make the blast directory
    os.makedirs(blast_dir)
    # and generate the blast database
    os.system(f'cat {args.reference_dir}/*.fasta | makeblastdb -dbtype nucl -out {blast_db} -title hpai_geno_db > /dev/null 2>&1')


    strain_records = {}
    for fasta in fastas:
        # need to iterate over all and make a dict with strain:[records]
        # iterate over all strains that have 8 segments (8 record entries)
        # and that aren't already annotated (if results.tsv exists)
        # for each, generate a temp fasta, run genoflu, and append results to .tsv
        for record in SeqIO.parse(fasta, 'fasta'):
            strain = record.id
            if strain not in annotated_strains:
                # if segment in segments:
                #     record.id =  f'{record.id}_{segment}'
                #     record.description = record.id
                try:
                    strain_records[strain].append(record)
                except KeyError:
                    strain_records[strain] = [record]

        for strain, records in strain_records.items():
            if len(records) == 8:
                i = 1
                # append sequential numbers to end of record ids to prevent duplicate key error
                for record in records:
                    record.id =  f'{record.id}_{str(i)}'
                    record.description = record.id
                    i += 1
                
                # write records to a temporary fasta file
                SeqIO.write(records, temp_fasta, 'fasta')

                # set up GenoFLU class
                genoflu = gf.GenoFLU(FASTA=temp_fasta, FASTA_dir=args.reference_dir,
                        cross_reference=args.cross_reference, sample_name=os.path.join(temp_dir, 'temp'), debug=False, blast_db=blast_db)
                # and run BLAST
                genoflu.blast_hpai_genomes()
                
                # get results/statistics using Excel_Stats class
                excel_stats = gf.Excel_Stats(genoflu.sample_name)
                genoflu.excel(excel_stats.excel_dict)
                FASTA_name = os.path.basename(temp_fasta)
                excel_stats.excel_dict["File Name"] = FASTA_name
                genoflu.excel_metadata(excel_stats.excel_dict)
                excel_stats.excel_dict["Genotype Average Depth of Coverage List"] = "Ran on FASTA - No Coverage Report"
                excel_stats.excel_dict["Strain"] = strain
                excel_stats.excel_dict['Date run'] = excel_stats.excel_dict['date']
                try:  # reorder stats columns
                    column_order = list(excel_stats.excel_dict.keys())
                    column_order.remove('sample')
                    column_order.remove('File Name')
                    column_order.remove('Strain')
                    column_order.remove('date')
                    column_order.insert(0, 'Strain')
                    column_order.remove('Genotype')
                    column_order.insert(1, 'Genotype')
                    excel_stats.excel_dict = {
                        k: excel_stats.excel_dict[k] for k in column_order}
                except ValueError:
                    pass

                # write results to the results.tsv file
                if not os.path.exists(results_tsv):
                    # if the file doesn't exist yet, set it up with dict keys as headers
                    # and write the data to the next line
                    with open(results_tsv, 'w') as f:
                        f.write('\t'.join(excel_stats.excel_dict.keys()))
                        f.write('\n'+'\t'.join(excel_stats.excel_dict.values()))
                else:
                    # otherwise, just write the data to the next line
                    with open(results_tsv, 'a') as f:
                        f.write('\n'+'\t'.join(excel_stats.excel_dict.values()))

                # print out a message in terminal with the strain's genotype and segment classifications
                print(f'\n{strain} Genotype --> {excel_stats.excel_dict["Genotype"]}: {excel_stats.excel_dict["Genotype List Used, >=98%"]}\n')

                # remove all temp files before running on the next strain
                for f in glob(os.path.join(temp_dir, '*')):
                    os.remove(f)

    # remove the temporary and blast directories
    shutil.rmtree(temp_dir)
    shutil.rmtree(blast_dir)