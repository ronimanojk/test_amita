#!/usr/bin/env python3
######################################################################
# Script for MR2 review automation                                   #
# 1. To be run by developer for reviewing the MR2 before making RFR  #
# 2. To be run by the reviewer/scheduler to review all RFR MR2       #
#                                                                    #
#    Date Modified : 19-02-2018                                      #
#    Version       : v1                                              #
#    Author        : Amita Banchhor                                  # 
######################################################################

import json
import getopt
import sys
import argparse
import re
import os.path
import getpass
import time
import requests
import logging
from io import open
from builtins import input

# To be updated while building exe for new versions
versionNumber = 1.1
releaseDate = '09 Mar 2018'
contactName = 'Amita Banchhor'
developer_version = 1  # 1 = check MRs defined by user (as arg or when prompted). And feedback results direct to user, 
                       # 0 = check MRs defined by user OR all MRs in certain state (e.g. RFR in title).  And feedback results to user AND update MR notes & tags

#Funtion to post the error messages on console and populate the error messages array to be used at the end for posting review report.
def post_error_comment(line) :
    global logger
    global fail_comments
    logger.error(line)
    fail_comments.append(line)
    return 

#Function to validate the MR2 under consideration.
def validate_mr(mr):
    global logger
    global sha_changes
    sha_changes = []
    logger.debug('MR Title: %s', mr['title'])
    logger.debug('MR ID: %s', mr['iid'])
    title_status = check_title(mr)
    save_sha_changes(mr['iid'])
    # description check based on title : whether for single WR/defect , multiple or GIT/other issues
    
    if title_status == "single" :
        check_single_desc(mr)
    if title_status == "multi" :
        check_multi_desc(mr)
    if title_status == "gitissue":
        check_gitissue_desc(mr)
    if title_status == "other":
        post_error_comment("Skipping further check because title is unclear.")
        print ("")
        input('Press Any Key to EXIT')
        sys.exit()		
    check_dependency()
    validate_testing(mr['source_branch'],mr['target_branch'])
    check_commit_history(mr['iid'])
    os.remove("MR2_desc.txt")
	
#Function to validate the Issue ID, WR/Defect ID and phase mentioned in description to be related as per the CQ Query Result offline data.
def ID_validation_clearquest(Issue_ID,ID,ID_Phase,target_branch):
    global CQ_Query_file
    cq_file = open(CQ_Query_file, "r")
    for line in cq_file:
        Iid,  WRID, DID, status, Phase, last = line.split("|",5)
        if Issue_ID == Iid:
            if ID == WRID or ID == DID:  
                if ID_Phase.upper() == Phase.upper():   #Comparing phase after converting both to uppercase to eliminate case sensitivity.
                    config_file = open("MR_review.cfg",'r')
                    for line in config_file:
                        if ((Phase in line) & (target_branch in line)):
                            config_file.close()
                            return 1
                      
                    post_error_comment("MR2 not raised for correct ngi/definitions branch")
                    config_file.close()
                    return 0
                else:
                    post_error_comment("Phase not mentioned same as the CQ Issue phase")
                    return 0
    post_error_comment("Issue or WR/Defect ID ("+ Issue_ID + " "+ID+") not found in CQ")
    return 0

#Function to check the title and then decide whether MR2 is for a single CQ item/multiple item/GIT Issue. 
def check_title(mr) :
    global CQ_Query_file
    global logger
    global title_flag
    if (re.findall(r"[Ss]ee *[Dd]escription",mr['title'])) :
        logger.debug("Multiple WR/Defect mentioned in this MR")
        title_flag = 1
        return "multi"
    elif (re.findall(r"[Gg][iI][tT] *[iI]ssue",mr['title'])) :
        git_issue = re.findall(r"[0-9]+",mr['title'])
        if check_git_issue(git_issue) :
            title_flag = 1
        return "gitissue"
    else:
        CQ_ids = re.findall(r"NGI[0-9]{8}",mr['title'])
        if len(CQ_ids) >= 2 :
            logger.debug("2 or more CQ IDs found in title, verifying them against the CQ dump")
            data_file = open(CQ_Query_file)
            for line in data_file :
                if CQ_ids[0] in line and CQ_ids[1] in line :
                    data_file.close()
                    logger.debug("CQ Ids mentioned in title is verified in the CQ dump")
                    title_flag = 1
                    return "single"
                    break
            if title_flag == 0:
                post_error_comment("CQ IDs mentioned in the Title is NOT verified in the CQ dump")
                return "single"
    post_error_comment("Title of the MR2 does not follow the guideline")
    return "other"
	
#Function to check the contents mentioned in Description for MR2 raised with respect to a GIT Issue
def check_gitissue_desc (mr) :
    desc_check_list = 0
    global logger
    global desc_flag
    global manual_comments
    desc_file = open("MR2_desc.txt",'wb')
    desc_file.write(mr['description'].encode("utf-8"))
    desc_file.close()
    desc_file = open("MR2_desc.txt",'r')
    comps = 0
    test_per = 0
    upload_flag = 0
    for line in desc_file :
        if (len(re.findall(r"[Tt]arget [Rr]elease [Pp]hase",line)) != 0 ) :
            desc_check_list=desc_check_list+1
            line = next(desc_file)
        if ((len(re.findall(r"[Gg][iI][tT] +[iI]ssue",line)) != 0 ) & (len(re.findall(r"[0-9]+",line))!=0) ) :
            comps=comps+1
            git_issue = re.findall(r"[0-9]+",line)[0]
            if git_issue in mr['title'] :
                desc_check_list = desc_check_list+1
            line2 = next(desc_file)
            if ( check_desc_title_git(line2) == 1):
                desc_check_list = desc_check_list+1
            for line_count in range(1,4):
                line4 = next(desc_file)
                if ( (len(re.findall(r"[iI]ssue *[Ss]olution",line4))!=0)):
                    if ( check_solution(line4) == 1 ):
                        desc_check_list = desc_check_list+1
                        break
            for line_count in range(1,10):
                line5 = next(desc_file)
                if (len(re.findall(r"[sS]ource *[cC]ode *[mM]erge *[rR]equest",line5))!=0):
                    if ( check_source_code(line5) == 1 ):
                        desc_check_list = desc_check_list+1
                    break
        if (desc_check_list == 5) :
            desc_flag = 1

    if  comps > 1 :
        logger.debug("Multiple components mentioned in description and title is for single component")
    desc_file.close()


#Function to validate the description of MR2 raised for a single CQ item.
def check_single_desc(mr) :
    desc_check_list = 0
    global desc_flag
    global logger
    global title_flag
    cq_state = 'NULL'
    desc_file = open("MR2_desc.txt",'wb')
    desc_file.write(mr['description'].encode("utf-8"))
    desc_file.close()
    desc_file = open("MR2_desc.txt",'r')
    comps = 0
    test_per = 0
    upload_flag = 0
    for line in desc_file :
        if (len(re.findall(r"[Tt]arget [Rr]elease [Pp]hase",line)) != 0 ) :
            mr2_phase = line.split(":",1)[1].strip()
            line = next(desc_file)
        if ((len(re.findall(r"[pP]arent [iI]ssue",line)) != 0 ) & (len(re.findall(r"NGI[0-9]{8}",line))!=0) ) :
            comps = comps + 1
            line2 = next(desc_file)
            if ( check_desc_ids(line,line2,mr2_phase,mr['target_branch']) == 1 ):
                desc_check_list = desc_check_list+1
            line3 = next(desc_file)
            if ( check_desc_title(line3) == 1):
                desc_check_list = desc_check_list+1
            line_state = next(desc_file)
            if ( (len(re.findall(r"[dD]efect *[Ss]tate *: *[vV]erified",line_state))!=0) | (len(re.findall(r"WR *[sS]tate *: *[dD]elivered",line_state))!=0)):
                desc_check_list = desc_check_list+1
                cq_state = 'validated'
            for line_count in range(1,4):
                line4 = next(desc_file)
                if ( (len(re.findall(r"[dD]efect/[wW][rR] *[Ss]olution",line4))!=0) | (len(re.findall(r"[dD]efect *[sS]olution",line4))!=0) | (len(re.findall(r"[wW][rR] *[sS]olution",line4))!=0) ):
                    if ( check_solution(line4) == 1 ):
                        desc_check_list = desc_check_list+1
                        break
            for line_count in range(1,10):
                line5 = next(desc_file)
                if (len(re.findall(r"[sS]ource *[cC]ode *[mM]erge *[rR]equest",line5))!=0):
                    if ( check_source_code(line5) == 1 ):
                        desc_check_list = desc_check_list+1
                    break
            if (desc_check_list == 5) :
                desc_flag = 1
            elif cq_state != 'validated' :
                post_error_comment("CQ WR/Defect State not changed to Delivered/Verified, respectively.")


    if  comps > 1 :
        logger.debug("multiple list in single comp title")
    desc_file.close()


#Function to validate the description of MR2 raised for multiple CQ items.
def check_multi_desc(mr) :
    global logger
    global desc_flag
    global component_count
    cq_state = 'NULL'
    desc_file = open("MR2_desc.txt",'wb')
    desc_file.write(mr['description'].encode("utf-8"))
    desc_file.close()
    desc_file = open("MR2_desc.txt",'r')
    comps = 0
    desc_check_list = 0
    desc_per_comp = 0
    upload_flag = 0
    for line in desc_file :
        if '# Tests performed' in line:
            break
        test_per = 0
        if (len(re.findall(r"[Tt]arget [Rr]elease [Pp]hase",line)) != 0 ) :
            mr2_phase = line.split(":",1)[1].strip()
            line = next(desc_file)
        if ((len(re.findall(r"[pP]arent [iI]ssue",line)) != 0 ) & (len(re.findall(r"NGI[0-9]{8}",line))!=0) ) :
            comps = comps + 1
            line2 = next(desc_file)
            if ( check_desc_ids(line,line2,mr2_phase,mr['target_branch']) == 1 ):
                desc_check_list = desc_check_list+1
            line3 = next(desc_file)
            if ( check_desc_title(line3) == 1):
                desc_check_list = desc_check_list+1
            line_state = next(desc_file)
            if ( (len(re.findall(r"[dD]efect *[Ss]tate *: *[vV]erified",line_state))!=0) | (len(re.findall(r"WR *[sS]tate *: *[dD]elivered",line_state))!=0)):
                desc_check_list = desc_check_list+1
                cq_state = 'validated'
            for line_count in range(1,4):
                line4 = next(desc_file)
                if ( (len(re.findall(r"[dD]efect/[wW][rR] *[Ss]olution",line4))!=0) | (len(re.findall(r"[dD]efect *[sS]olution",line4))!=0) | (len(re.findall(r"[wW][rR] *[sS]olution",line4))!=0) ):
                    if ( check_solution(line4) == 1 ):
                        desc_check_list = desc_check_list+1
                        break
            for line_count in range(1,10):
                line5 = next(desc_file)
                if (len(re.findall(r"[sS]ource *[cC]ode *[mM]erge *[rR]equest",line5))!=0):
                    if ( check_source_code(line5) == 1 ):
                        desc_check_list = desc_check_list+1
                    break
            if (desc_check_list == 5) :
                desc_per_comp = desc_per_comp+1
                desc_check_list = 0
            elif cq_state != 'validated' :
                post_error_comment("CQ WR/Defect State not changed to Delivered/Verified, respectively.")

    if desc_per_comp == comps :
        desc_flag = 1

    component_count = comps
    desc_file.close()

#Function to validate testing information in description section.
def validate_testing(source_branch, target_branch):
    global tests_flag
    upload_flag = 0
    test_per = 0
    file_ptr = open("MR2_desc.txt",'r')
    for line in file_ptr:
        if (((len(re.findall(r"Subsystem Testing Report",line))) != 0)):
            if "/uploads/" in line:
                logger.debug("Test Report is found to be attached")
                upload_flag = 1
            else:
                line = next(file_ptr)
                if "/uploads/" in line :
                    upload_flag = 1
                    logger.debug("Test Report is found to be attached")
                else:
                    post_error_comment("Test performed but report not attached")
        if "Test performed in full rootfs" in line :
            if ( (("yes" in line) != 0) | (("Yes" in line) != 0) | (("YES" in line)!=0 )):
                #logger.info("Rootfs tested pipeline verification: Pass")
                test_per = 1
            else:
                if ( (("NO" in line) != 0) | (("No" in line) != 0) | (("no" in line)!=0 )):
                    post_error_comment("Test not performed in full rfs, please verify the reason")
        if ( (upload_flag != 0) & (test_per != 0)):
            tests_flag=1

        if ((len(re.findall(r"Link to Pipeline where RFS was taken for Testing",line))) != 0) :
            pipeline_check(line,source_branch,target_branch)

    file_ptr.close()

#Function to validate dependent MR and dependent Issues.
def check_dependency():
    global dependent_issue_flag
    global dependent_mr_flag

    file_ptr = open("MR2_desc.txt",'r')
    for line in file_ptr:
        if "# Dependent issues" in line :
            while True:
                line = next(file_ptr)
                if (line.startswith("#")):
                    break
                else:
                    if "NA" not in line:
                        dep_issue = re.findall(r"NGI[0-9]+",line)
                        if len(dep_issue) != 0 :
                            if issue_validation_clearquest (dep_issue) :
                                dependent_issue_flag = 1
                            else:
                                dependent_issue_flag = 0
                    else:
                        dependent_issue_flag=1
                        break
 
        if "# Dependent MR" in line :
            while True:
                line = next(file_ptr)
                if (line.startswith("#")):
                    break
                else:
                    if "NA" not in line:
                        dep_mr = re.findall(r"[0-9]+",line)
                        if len(dep_mr) != 0 :
                            if check_for_merged (dep_mr[0]) :
                                dependent_mr_flag = 1
                            else:
                                dependent_mr_flag = 0
                    else:
                        dependent_mr_flag=1
                        break
    file_ptr.close()


#Function to check the credibility of the Git Issue mentioned in description of MR2 raised to resolve a GIT Issue.
def check_git_issue (git_issue):
    global logger
    global session
    global session
    url = 'https://git.jlrngi.com/ngi/definitions/issues/'+str(git_issue[0])
    headersData = {'content-type': 'application/json'}
    req_return = session.get(url, headers=headersData)
    if req_return.status_code == 200:
        logger.debug('GIT issue id is a valid Issue ID')
        return 1
    else:
        post_error_comment('Invalid GIT issue id')
        return 0

#Function to parse the WR/Defect ID, Issue ID and phase from the description text to be used for ID_validation_clearquest.
def check_desc_ids(line,line2,mr2_phase,target_branch) :
    global logger
    try:
        issue_id = re.findall(r"NGI[0-9]{8}",line)[0]
    except IndexError:
        logger.debug("WR/Defect ID mentioned incorrect")
        return 0
    logger.debug("Issue ID: %s", issue_id)
    link = "http://www.ngicq.jlrint.com/cqweb/#/8.0.0/NGI/RECORD/"+issue_id
    if link in line :
        logger.debug("Issue id link mentioned correctly.")
    else :
        post_error_comment("Issue id link NOT mentioned correctly.")
        return 0
    if ( (len(re.findall(r"[dD]efect/[wW][rR] *CQID",line2))!=0) | (len(re.findall(r"[dD]efect *CQID",line2))!=0) | (len(re.findall(r"[wW][rR] *CQID",line2))!=0) ) :
        try :
            wrdef_id = re.findall(r"NGI[0-9]{8}",line2)[0]
        except IndexError:
            logger.debug("WR/Defect ID mentioned incorrect")
            return 0
        logger.debug("WR ID: %s", wrdef_id)
        link = "http://www.ngicq.jlrint.com/cqweb/#/8.0.0/NGI/RECORD/"+wrdef_id
        if link in line2 :
            logger.debug("WR/Defect id link mentioned correctly.")
            if len(re.findall(r"[dD]efect/[wW][rR] *CQID",line2))!=0 :
                post_error_comment("Defect/WR CQID should be changed to either WR or Defect")
                return 0
        else :
            post_error_comment("WR/Defect id link NOT mentioned correctly.")
            return 0

    if ID_validation_clearquest(issue_id,wrdef_id,mr2_phase,target_branch) :
        return 1
        
#Function to check if the title field in description of MR2 is not empty.
def check_desc_title(line):
    global logger
    if ( (len(re.findall(r"[dD]efect/[wW][rR] *[tT]itle",line))!=0) | (len(re.findall(r"[dD]efect *[tT]itle",line))!=0) | (len(re.findall(r"[wW][rR] *[tT]itle",line))!=0) | (len(re.findall(r"[Gg][iI][tT] *[iI]ssur *[tT]itle",line))!=0)) :
        try :
            title = line.split(":",1)[1]
        except IndexError :
            post_error_comment("Title not mentioned as per the template")
            return 0
        if len(title) > 3:
            logger.debug("Title is not empty")
            if len(re.findall(r"[dD]efect/[wW][rR] *[tT]itle",line))!=0 :
                post_error_comment("Defect/WR Title should be changed to either WR or Defect")
                return 0
            return 1
        else:
            post_error_comment("Title in description is empty.")
    return 0

##Function to check if the title field in description of MR2(for GIT Issues) is not empty.
def check_desc_title_git(line):
    global logger
    if (len(re.findall(r"[iI]ssue *[tT]itle",line))!=0):
        try :
            title = line.split(":",1)[1]
        except IndexError :
            post_error_comment("Title mentioned incorrectly.")
            return 0
        if len(title) > 3:
            logger.debug("Title is not empty")
            return 1
        else:
            post_error_comment("Title in description is empty.")
        return 0

#Function to check if the Solution field in description of MR2 is not empty.
def check_solution(line):
    try:
        solution = line.split(":",1)[1]
    except IndexError:
        post_error_comment("Solution not mentioned as per the template")

    if len(solution) != 0:
        logger.debug("Solution is not empty")
        if len(re.findall(r"[dD]efect/[wW][rR] *[sS]olution",line))!=0 :
            post_error_comment("Defect/WR Solution should be changed to either WR or Defect")
            return 0
        return 1
    else:
        post_error_comment("Solution is empty.")
    return 0

#Function to check the MR1 link validity mentioned in the MR2
def check_source_code(line):
    global logger
    global mr1_sha
    global session
    source_code = line.split(":",1)[1]
    if len(source_code) != 0:
        logger.debug("Source code is not empty")
        source_parts = source_code.split("/",9)
        if len(source_parts) == 7 :
            logger.debug("source code link format mentioned correctly.")
        else :
            post_error_comment("Description verification: Fail. Source code link wrong")           
            return 0
        try:
            source_mr_id = re.findall(r"[0-9]+",source_parts[6])[0]
        except IndexError:
            post_error_comment("MR1 id could not be retrieved.")
            return 0
        url = 'https://git.jlrngi.com/api/v4/projects?search='+source_parts[4] 
        headersData = {'content-type': 'application/json'}
        req_return = session.get(url, headers=headersData)
        if req_return.status_code == 200:
            data = req_return.json()
            if len(data) != 0:
                for searchResult in data:
                    source_project = searchResult
                    if source_project['path_with_namespace'] == source_parts[3] + '/' + source_parts[4]:
                        source_project_id = source_project['id']
                        break
            else:
                post_error_comment("Source project data not entered well in the MR1 source.")
                return 0

        if source_parts[3] == "stc" :
            url = 'https://git.jlrngi.com/api/v4/projects/'+str(source_project_id)+'/merge_requests/'+str(source_mr_id)
            req_return = session.get( url, headers=headersData)
            if req_return.status_code == 200:
                source_mr = req_return.json()
            else :
                post_error_comment("MR1 merge details could not be fetched")
                return 0

            if source_mr['state'] == "merged" :
                logger.debug("MR1 is merged")
                mr1_sha = source_mr['merge_commit_sha']
                logger.debug("Merge SHA: %s", mr1_sha)
                logger.debug("Source MR Target branch: %s", source_mr['target_branch'])
                sha_line = "+  sha: "+mr1_sha
                if sha_line in sha_changes:
                    return 1
                else:
                    post_error_comment("MR1 is merged but sha not mentioned correctly in MR2")
            else :
                post_error_comment("MR1 is NOT merged")
    return 0

#Function to validate the pipeline mentioned in testing part to be from the correct source branch and to have clear pipeline log.
def pipeline_check(line,source_branch,target_branch):
    global logger
    global rootfs_flag
    global session
    global ngi_def_project_id
    pipeline_id_str = line.split('/pipelines/',1)
    if (len(pipeline_id_str)) == 2:
        pipeline_id = re.findall(r"[0-9]*",pipeline_id_str[1])[0]
        # Compose URl for MR (hardcoded for now) and get it
        headersData = {'content-type': 'application/json'}
        url = 'https://git.jlrngi.com/api/v4/projects/'+str(ngi_def_project_id)+'//pipelines/'+pipeline_id+'/jobs'
        req_ret = session.get(url, headers=headersData)
        if req_ret.status_code == 200:
            pipeline_data = req_ret.json()
            # loop through all items in data dict and find the ngi-branch-status, then get job id
            for item in pipeline_data:
                if item['name'] == "ngi-branch-status":
                    jobID = item['id']
            logger.debug("Job Id ngi-branch-status is %s", jobID)

            logger.debug("Looking for log file with 'is behind <branch> by 0 commits'")
            # Compose URl for MR (hardcoded for now) and get it
            url = 'https://git.jlrngi.com/api/v4/projects/'+str(ngi_def_project_id)+'/jobs/' + str(jobID) + '/trace'   # TODO - make pid dynamic
            req_return = session.get(url, headers=headersData)
            if req_return.status_code == 200:
                # check the result for the required string (hardcoded the branch for now)
                msg_check = "The Branch "+source_branch+" is behind "+target_branch+" by 0 commits"
                if msg_check in req_return.text:
                    logger.debug("Correct source and target branch for pipeline and behind 0 commits")
                    rootfs_flag = 1
                else:
                    post_error_comment("Cannot confirm clean pipeline log")
            else:
                post_error_comment("Couldn't find the trace data for the job")
        else:
           post_error_comment("Couldn't find pipeline jobs")
    else:
        post_error_comment("Pipeline link not mentioned correctly")
        rootfs_flag=0

#Function to check the dependent MR to be merged.
def check_for_merged(dep_mr) :
    global logger
    global ngi_def_project_id
    global session
    headersData = {'content-type': 'application/json'}
    for dmr in dep_mr :
        url = 'https://git.jlrngi.com/api/v4/projects/'+str(ngi_def_project_id)+'/merge_requests/'+str(dep_mr)
        req_return = session.get(url, headers=headersData)
        if req_return.status_code == 200:
            mr = req_return.json()
            if mr['state'] == "merged" :
                logger.debug("Dependent MRs merged")
                return 1
            else :
                post_error_comment("Dependent MRs NOT merged")
                return 0
        else:
            post_error_comment("Could not retrieve dependent MR details.")
            return 0

#Function to validate the dependent Issue to be in validating state. -- TBD
def issue_validation_clearquest(Issue_ID):
    global logger
    global CQ_Query_file
    cq_file = open(CQ_Query_file, 'r')
    for line in cq_file:
        Iid,  WRID, DID, state, Phase,last = line.split("|", 5)
        if Issue_ID == Iid and state == "Validating":
            cq_file.close()
            return 1
    cq_file.close()
    return 0

#Function to save the changes done in source branch in an accessible array for reference.
def save_sha_changes(mr_iid):
    global mr1_sha
    global sha_changes
    global manual_comments
    global session
    global ngi_def_project_id
    # Compose URl for MR (hardcoded for now) and get it
    url = 'https://git.jlrngi.com/api/v4/projects/'+str(ngi_def_project_id)+'/merge_requests/'+str(mr_iid)+'/changes'  # TODO - make pid and iid dynamic
    headersData = {'content-type': 'application/json'}
    rchanges = session.get(url, headers=headersData)
    # check status to ensure we get 200
    if rchanges.status_code == 200:
        logger.debug("got the MR change data")
        change_data = rchanges.json()
        # let's loop through everything in 'changes'
        for change_item in change_data['changes']:
            fileName = change_item['new_path']
            if (("morph" in fileName) & (len(fileName.split('/',5)) == 4) | ("morph" not in fileName) ):
#                post_error_comment ("component morph file or yml file changed, manual review needed.")
                logger.warning ("component morph file or yml file changed, manual review needed.")
                manual_comments.append("component morph file or yml file changed, manual review needed.")
            diff = change_item['diff']
            # loop through each line in the changes
            for line in diff.splitlines():
                # if we find a new sha then print it along with the filename
                if "+  sha: " in line:
                    sha_changes.append(line)
                if (("+  ref: " in line) & ("+  ref: ngi/master" not in line) ):
                    logger.warning ("component reference branch changed in morph file, manual review needed.")
                    manual_comments.append("component reference branch changed in morph file, manual review needed.")
    else:
        post_error_comment( "Couldn't find the MR changes")

#Function to check the commit history in the MR2.
def check_commit_history(mr_iid) :
    commit_count = 0
    global manual_comments
    global commit_history_flag
    global session
    global ngi_def_project_id
    logger.debug("component count inside commit check = %d ",component_count)
    commmit_url = 'https://git.jlrngi.com/api/v4/projects/'+str(ngi_def_project_id)+'/merge_requests/'+str(mr_iid)+'/commits'
    headersData = {'content-type': 'application/json'}
    rcommit = session.get(commmit_url, headers=headersData)
    # check status to ensure we get 200
    if rcommit.status_code == 200:
       	logger.debug("got the MR commit history data")
        commit_data = rcommit.json()
        py_version = int(sys.version_info[0])
        if py_version == 2:
            commit_file = open("commit_desc.txt",'wb')
        if py_version == 3:
            commit_file = open("commit_desc.txt",'w')   
        json.dump(commit_data, commit_file)
        commit_file.close()
        commit_file = open("commit_desc.txt",'r')
        #print commit_data
        commit_count = len(commit_data)
        if commit_count == 1:
            logger.debug("1 commit found in MR -Commit history seems Good")
            commit_history_flag = 1
        elif commit_count == 0:
            post_error_comment("Commit count = 0, make a commit to be merged by this MR2") 
        elif (commit_count<=component_count) :
            warning_message="Number of commits is more than 1 -Commit history need to check manually. Commit count = "+str(commit_count)
            logger.warning(warning_message)
            manual_comments.append(warning_message)
            commit_history_flag = 1
        elif commit_count > component_count:
            post_error_comment("Number of commit found to be more than number of components, need to squash")
            commit_history_flag = 0
        else:
            post_error_comment("No commit done for the MR branch -Commit the changes 1st and then Request for merge.")
            commit_history_flag = 0
    else:
        post_error_comment("Couldn't find the MR commit history")
    commit_file.close()
    os.remove("commit_desc.txt")

#Function to print report to console as well as preparing the report message to be posted for RFR MR2s.
def print_Report(mr_iid):
    global title_flag
    global desc_flag
    global rootfs_flag
    global report_message
    global dependent_mr_flag
    global dependent_issue_flag
    global tests_flag
    merge_flag = 1
    # final report
    if title_flag == 1:
        logger.info("PASS - Title verification")
        report_message.append("PASS - Title verification")
    else:
        merge_flag = 0
        logger.info("FAIL - Title verification")
        report_message.append("FAIL - Title verification")

    if desc_flag == 1:
        logger.info("PASS - Description verification")
        report_message.append("PASS - Description verification")
    else:
        merge_flag = 0
        logger.info("FAIL - Description verification")
        report_message.append("FAIL - Description verification")

    if tests_flag == 1:
        logger.info('PASS - Tests performed verification')
        report_message.append('PASS - Tests performed verification')
    else :
        merge_flag = 0
        logger.info('FAIL - Tests performed verification')
        report_message.append('FAIL - Tests performed verification')
    if dependent_mr_flag == 1:
        logger.info('PASS - Dependent MR verification')
        report_message.append('PASS - Dependent MR verification')
    else :
        logger.info('FAIL - Dependent MR verification')
        report_message.append('FAIL - Dependent MR verification')
        merge_flag = 0
    if dependent_issue_flag == 1:
        logger.info('PASS - Dependent Issue verification')
        report_message.append('PASS - Dependent Issue verification')
    else :
        logger.info('FAIL - Dependent Issue verification')
        report_message.append('FAIL - Dependent Issue verification')
        merge_flag = 0

    logger.info('TBD  - Documentation for component verification @ https://git.jlrngi.com/ngi/documentation/wikis/ngi-components-documentation')
    logger.info('TBD  - Gate1 compliance review verification (verification by [CDSID of reviewer to be added])')

    if rootfs_flag == 1:
        logger.info('PASS - Rootfs tested pipeline verification')
        report_message.append('PASS - Rootfs tested pipeline verification')
    else:
        merge_flag = 0
        logger.info('FAIL - Rootfs tested pipeline verification')
        report_message.append('FAIL - Rootfs tested pipeline verification')
    if commit_history_flag == 1:
        logger.info('PASS - Commit history verification')
        report_message.append('PASS - Commit history verification')
    else:
        merge_flag = 0
        logger.info('FAIL - Commit history verification')
        report_message.append('FAIL - Commit history verification')
    if merge_flag == 1 :
        logger.info('Merge Request %s has been approved', mr_iid)
        message = 'Merge Request %s has been approved',str( mr_iid)
    else :
        logger.info('Merge Request %s has NOT been approved', mr_iid)
        message = 'Merge Request %s has NOT been approved',str( mr_iid)


#Function to post the review comments and report to the MR2 discussion for RFR MR2s.
def post_to_mr(mr):
    global fail_comments
    global manual_comments
    global session
    global ngi_def_project_id
    manual_message = ''
    fail_message=''
    headersData = {'content-type': 'application/json'}
    url = 'https://git.jlrngi.com/api/v4/projects/'+str(ngi_def_project_id)+'/merge_requests/'+str(mr['iid'])+'/notes'
    url_label = 'https://git.jlrngi.com/api/v4/projects/'+str(ngi_def_project_id)+'/merge_requests/'+str(mr['iid'])
    report_message_post = '<br>'.join(report_message)
    
    
    status =  session.get(url_label, headers=headersData)
    data = status.json()
    label_array = data['labels']
    if 'Failed Automated Check' in label_array :
        label_array.remove('Failed Automated Check')
    if 'Manual Review Needed' in label_array :
        label_array.remove('Manual Review Needed')
    if 'Passed Automated Check' in label_array :
        label_array.remove('Passed Automated Check')
    
    if (len(fail_comments) != 0 ):
        label_array.append('Failed Automated Check')
        fail_message = '<br>'.join(fail_comments)
    if (len(manual_comments) != 0 ):
        label_array.append('Manual Review Needed')
        manual_message = '<br>'.join(manual_comments)
    
    if ((len(manual_comments) == 0 ) & (len(fail_comments) == 0 )) :
        label_array.append('Passed Automated Check')
        commentData = '{"body":"'+'===REPORT==='+'<br>'+report_message_post+'"}'
    else :    
        commentData = '{"body":"---FAIL---<br>'+fail_message+'<br>---MANUAL CHECK---<br>'+manual_message+'<br>'+'===REPORT==='+'<br>'+report_message_post+'"}'
    status = session.post(url, headers=headersData, data=commentData)
    
    label_content = ','.join(label_array)
    labelData = '{"labels":"'+label_content+'"}'
    status = requests.put(url_label, headers=headersData, data=labelData)

def global_var_initialization():
#####################################################################################
#define variables to track and report status of each tickbox in MR
#####################################################################################
    global CQ_Query_file
    global title_flag
    global desc_flag
    global tests_flag
    global mr1_sha
    global dependent_mr_flag
    global dependent_issue_flag
    global cleanGit_flag
    global documentaion_flag
    global gate1_flag
    global rootfs_flag
    global changes_flag
    global commit_history_flag
    global fail_comments
    global manual_comments
    global component_count
    global report_message
    global logger
    CQ_Query_file =  "CQ_QueryResult.txt"
    report_message=[]
    fail_comments = []
    manual_comments = []
    changes_flag=0
    title_flag = 0
    desc_flag = 0
    tests_flag = 0
    dependent_mr_flag = 1
    dependent_issue_flag = 1
    cleanGit_flag = 0
    documentaion_flag = 0
    gate1_flag = 0
    mr1_sha = 0
    rootfs_flag = 0
    commit_history_flag = 0
    component_count = 1
	
#####################################################################################
#--------------------------------main ()----------------------------------------------
#####################################################################################

def main():
    global CQ_Query_file
    global logger
    global session
    global session
    global_var_initialization()
    global ngi_def_project_id
    global config_content
    ngi_def_project_id = 958
    session = requests.Session()
    #####################################################################################
    # parse the arguments
    #####################################################################################
    parser = argparse.ArgumentParser(description='MR2 review')
    parser.add_argument('--mr2', '-m', required=False, help='MR2 id for which review is to be done')
    parser.add_argument('--level', '-l', required=False, help='Logging level (INFO (default), DEBUG, WARNING, CRTIICAL')
    parser.add_argument('--version', '-v', action='store_true', required=False, help='Show version number and exit')
    
    args = parser.parse_args()
    
    if args.version :
        print ('Version number: '+str(versionNumber))
        print ('Release date : '+releaseDate)
        print ('Contact: '+contactName)
        input('Press Any Key to EXIT')
        sys.exit()
    
    #####################################################################################
    # Configure logging
    # If no logging level provided then default to INFO
    #####################################################################################
    logger = logging.getLogger(__name__)
    if args.level is None :
        args.level = "INFO"
    # Check if valid Log level and set, if not default back to INFO
    numeric_level = getattr(logging, args.level.upper(), None)
    if not isinstance(numeric_level, int):
        print(('Invalid log level: %s, using INFO \n' % args.level))
        logger.setLevel(logging.INFO)
    else :
        logger.setLevel(numeric_level)
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(levelname)s: \t%(message)s')
    ch.setFormatter(formatter)
    logger.addHandler(ch)
    
    #####################################################################################
    # check for and read the cfg file
    #####################################################################################
    if not(os.path.exists('MR_review.cfg')) :
        logger.critical('Can not find config file: MR_review.cfg')
        print ("")
        input('Press Any Key to EXIT')
        sys.exit()
        
    #####################################################################################
    # check for local CQ list
    #####################################################################################
    if os.path.exists(CQ_Query_file) :
        print(("Using CQ file 'CQ_QueryResult.txt' dated on " + time.strftime('%d/%B/%Y', time.gmtime(os.path.getmtime('CQ_QueryResult.txt')))))
    else :
        logger.critical("CQ file is missing.  Download data from CQ to CQ_QueryResult.txt")
        print ("")
        input('Press Any Key to EXIT')
        sys.exit ()
    
    #####################################################################################
    # prompt user for uid and password and authenticate user
    #####################################################################################
    print("")
    usernamefromFile=""
    if os.path.exists('.gitLabUsername.txt') :
        usernameFile = open('.gitLabUsername.txt','r')
        usernamefromFile=usernameFile.read()
        usernameFile.close()
    user_email = input('Enter email I\'d (' + str(usernamefromFile) + '):')
    if (user_email == "") :
        user_email = usernamefromFile
    else :
        usernameFile = open('.gitLabUsername.txt','wb')
    #    usernameFile.write(bytes(user_email, 'UTF-8'))
    #    usernameFile = open('.gitLabUsername.txt','wt')
        usernameFile.write(user_email)
        usernameFile.close()
    userspassword = getpass.getpass("Enter password: ")
    print("")
    logger.debug('Authentication successful for user %s', user_email)
    
    #####################################################################################
    # process the MR(s)
    #####################################################################################

    SIGN_IN_URL = 'https://git.jlrngi.com/users/sign_in'
    session = requests.Session()
    sign_in_page = str(session.get(SIGN_IN_URL).content)
    sign_in_page_ar = sign_in_page.split('\n')
    for sign_in_lines in sign_in_page_ar:
        search_ret = re.search('name="authenticity_token" value="([^"]+)"', sign_in_lines)
        if search_ret:
            break
    
    token = None
    if search_ret:
        token = search_ret.group(1)
    
    if not token:
        print('Unable to find the authenticity token')
        sys.exit(1)
    
    session_data = {'user[login]': user_email,
            'user[password]': userspassword,
            'authenticity_token': token}
    req_ret = session.post(SIGN_IN_URL, data=session_data)
    if req_ret.status_code != 200:
        logger.critical('Failed to log in')
        input('Press Any Key to EXIT')
        sys.exit(1)
    elif "Invalid Login or password." in req_ret.text:
        logger.critical('Invalid Login or password.')
        sys.exit(1)
    
    headersData = {'api_version': '3', 'session': str(session)}
    req_ret = session.post('https://git.jlrngi.com', headers=headersData)
    headersData = {'content-type': 'application/json'}

    if developer_version:                                       # if to be run by developer and output only to screen
        if args.mr2:                                            # if user provided MR2 as argument
            mr2_id = args.mr2
        else:                                                   # if user didn't provide MR2 as argument
            try:
                mr2_id = (input('Enter MR2 ID to be reviewed:')).split()[0]
            except IndexError as error:
                logger.critical('MR2 number not entered')
                print("")
                input('Press Any Key to EXIT')
                sys.exit()
        print("")
        url = 'https://git.jlrngi.com/api/v4/projects/'+str(ngi_def_project_id)+'/merge_requests/'+mr2_id
        req_return = session.get(url, headers=headersData)
        if req_return.status_code != 200:
            logger.critical('Unable to get %s', url)
            print ("")
            input('Press Any Key to EXIT')
            sys.exit()
        else :
            mr = req_return.json()
            validate_mr(mr)
            print ("")
            print_Report(mr['iid'])
            print ("")
            input('Press Any Key to EXIT')
            sys.exit()
    else :                                                      # if to be run with output to screen and MR notes/tags updated
        if args.mr2:                                            # if user provided MR2 as argument
            mr2_id = args.mr2
            url = 'https://git.jlrngi.com/api/v4/projects/'+str(ngi_def_project_id)+'/merge_requests/'+mr2_id
            req_return = session.get(url, headers=headersData)
            if req_return.status_code != 200:
                logger.critical('Unable to get %s', url)
                print ("")
                input('Press Any Key to EXIT')
                sys.exit()
            else :
                mr = req_return.json()
                logger.info('Merge Request %s', mr['iid'])
                logger.info('==================')
                validate_mr(mr)
                print_Report(mr['iid'])
                post_to_mr(mr)
                global_var_initialization()
                input('Press Any Key to EXIT')
                sys.exit()
        else :                                                  # if user didn't provide MR2 as argument, find all MR2s for checking
            pageNumber = 1
            while True:
                url = 'https://git.jlrngi.com/api/v4/projects/'+str(ngi_def_project_id)+'/merge_requests?scope=all&utf8=%E2%9C%93&state=opened&page='+str(pageNumber)+'&per_page=100'
                req_return = session.get(url, headers=headersData)
                if req_return.text == '[]':
                    break
                pageNumber += 1
                if req_return.status_code != 200:
                    logger.critical('Unable to get %s', url)
                    input('Press Any Key to EXIT')
                    sys.exit()
                else :
                    mr_list = req_return.json()
                    mr_count = len(mr_list)
                    mr_index = 0
                    for mr_index in range (0,mr_count):
                        mr = mr_list[mr_index]
                        if "TESTING" in mr['title']:
                            print("\n\n")
                            logger.info('Merge Request %s', mr['iid'])
                            logger.info('==================')
                            validate_mr(mr)
                            print_Report(mr['iid'])
                            post_to_mr(mr)
                            global_var_initialization()
                            input('Press Any Key to EXIT')
                            sys.exit(1)
                            

if __name__ == "__main__":
    main()

	