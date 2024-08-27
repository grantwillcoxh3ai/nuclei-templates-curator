import os
import re
import csv
import shutil
import json
import asyncio
import tempfile
import subprocess
import requests
import time
import hashlib
import zipfile
import platform

requests.packages.urllib3.disable_warnings()

# md5
def md5(msg, encoding='utf8'):
    return hashlib.md5(msg.encode(encoding)).hexdigest()

# Read GitHub project links from the file listed in file_path
def read_github_links(file_path):
    links = []
    # Read the CSV file, usually links.csv
    with open(file_path, 'r') as f:
        reader = csv.reader(f)
        next(reader)  # Skip the header row
        for row in reader:
            if row[0].startswith('https://github.com'):
                links.append(row[0])  # Extract links and add to list
    return links

# Add in GitHub links
def append_github_links(file_path, links):
    # Append links to CSV file
    with open(file_path, 'a', newline='') as f:
        writer = csv.writer(f)
        for link in links:
            writer.writerow([link])  # Write the link

# Search for projects that contain nuclei-templates somehow.
def search_projects():
    token = os.getenv("GH_TOKEN", "")
    headers = {
        "Authorization": f"{token}",
        "Connection": "close",
        "User-Agent": "Mozilla/5.0 (Windows NT 6.1; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/64.0.3282.119 Safari/537.36",
    }
    # Send a search request to GitHub API
    search_url = "https://api.github.com/search/repositories?q=nuclei-templates&sort=updated&page=1&per_page=100"
    response = requests.get(search_url, headers=headers,
                            verify=False, allow_redirects=False).json()
    print(response)

    # Extract the list of projects from the response
    projects = [i['html_url'] for i in response.get("items", [])]

    # Return the list of projects
    return projects

# Verify the YAML files we downloaded using Nuclei
def nuclei_validate(temp_directory):
    current_directory = os.path.join(os.getcwd(),'nuclei-templates')
    nuclei_path = download_extract_executable(temp_directory)
    command = f'{nuclei_path} -validate -t {current_directory}'
    try:
        output = subprocess.check_output(
            command, shell=True, stderr=subprocess.STDOUT, universal_newlines=True)
    except subprocess.CalledProcessError as e:
        output = e.output
    err_pattern = r"Error occurred (?:loading|parsing) template (.*?)\:"
    for err_match in re.findall(err_pattern, output):
        file_path = err_match.replace("\\", "/")  # Convert backslashes in file path into forward slashes
        if os.path.exists(file_path):
            os.remove(file_path)
            print(f"Deleted file: {file_path}")
    warn_pattern = r"Found duplicate template ID during validation '(.*?)' => '(.*?)'\:"
    for warn_match in re.findall(warn_pattern, output):
        old_path = warn_match[0].replace("\\", "/")
        new_path = warn_match[1].replace("\\", "/")
        if os.path.exists(old_path):
            shutil.move(old_path, new_path)
            print(f"Renamed file: {old_path} to {new_path}")

# Extract the nuclei binary for validation from the ZIP files.
def download_extract_executable(temp_directory):
    system = platform.system()
    if system == 'Windows':
        zip_file_path = './nuclei/nuclei_3.1.10_windows_amd64.zip'
    else:
        zip_file_path = './nuclei/nuclei_3.1.10_linux_amd64.zip'

    # Unzip the compressed file
    extract_dir = os.path.join(temp_directory, "extracted")
    with zipfile.ZipFile(zip_file_path, 'r') as zip_ref:
        zip_ref.extractall(extract_dir)

    # Add execute permissions to the unzipped Nuclei binary
    for executable in os.listdir(extract_dir):
        if 'nuclei' in executable:
            executable_path = os.path.join(extract_dir, executable)
            os.chmod(executable_path, 0o755)
            print(executable_path)
    # Return the full path to the Nuclei executable
    return executable_path

# Iterate through the .yaml files in the temporary directory
def process_yaml_files(temp_directory):
    # Create a destination folder
    target_directory = os.path.join(os.getcwd(),'nuclei-templates', 'Other')
    os.makedirs(target_directory, exist_ok=True)

    # Traverse the temporary directories, looking for .yaml files
    for root, _, files in os.walk(temp_directory):
        for file in files:
            if file.endswith('.yaml'):
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, 'r', encoding='utf8') as f:
                        content = f.read()
                except:
                    continue

                # Determine whether the file content contains at least 5 keywords that are found by default in Nuclei templates.
                if len([tag for tag in ['id:', 'info:', 'name:', 'author:', 'severity:', 'description:', 'tags:', 'requests:', 'matchers:'] if tag in content]) > 5:
                    # Determine whether the file name matches CVE-\d{4}
                    match = re.match(r'CVE-\d{4}', file, re.I)
                    if match:
                        target_folder = os.path.join(
                            os.getcwd(),'nuclei-templates', match.group().upper())
                        os.makedirs(target_folder, exist_ok=True)
                        target_path = os.path.join(target_folder, file)
                    else:
                        target_path = os.path.join(target_directory, file)

                    # Copy the file to the destination path
                    shutil.copy2(file_path, target_path)


# 统计临时目录中的.yaml文件
def count_yaml_files(temp_directory, links):
    count = {}
    for link in links:
        # 遍历临时目录
        for root, _, files in os.walk(os.path.join(temp_directory, md5(link))):
            for file in files:
                if file.endswith('.yaml'):
                    file_path = os.path.join(root, file)
                    try:
                        with open(file_path, 'r', encoding='utf8') as f:
                            content = f.read()
                    except:
                        continue
                    # Determine whether the file content contains at least 5 of the keywords that would be included by default in a Nuclei template.
                    if len([tag for tag in ['id:', 'info:', 'name:', 'author:', 'severity:', 'description:', 'tags:', 'requests:', 'matchers:'] if tag in content]) > 5:
                        count.setdefault(link, 0)
                        count[link] += 1
    return count

# Clean up the Nuclei templates once we are done using them.
def clear_file():
    # Current directory path
    current_directory = os.path.join(os.getcwd(),'nuclei-templates')
    # 递归遍历文件
    for root, dirs, files in os.walk(current_directory):
        for file in files:
            full_file = os.path.join(root, file)
            if re.match('.*?-[0-9a-fA-F]{32}',file):
                new_file = re.sub('-[0-9a-fA-F]{32}','',file)
                new_full_file = os.path.join(root,new_file)
                if os.path.exists(new_full_file):
                    os.remove(full_file)
                    continue
                else:
                    poc_code = open(full_file,'r',encoding='utf8').read()
                    poc_code = poc_code.replace(os.path.splitext(file)[0],os.path.splitext(new_file)[0])
                    with open(new_full_file,'w',encoding='utf8') as f:
                        f.write(poc_code)

    for dir1 in os.listdir(current_directory):
        if dir1.lower().startswith('cve'):
            for file in os.listdir(os.path.join(current_directory,dir1)):
                if re.match('^cve-\d+-\d+\.yaml$',file,re.I):
                    continue
                if re.match('cve-\d+-\d+',file,re.I):
                    new_file = re.findall('(cve-\d+-\d+)',file,re.I)[0] + '.yaml'
                    if os.path.exists(os.path.join(current_directory,dir1,new_file)):
                        os.remove(os.path.join(current_directory,dir1,file))
                    try:
                        os.rename(os.path.join(current_directory,dir1,file),os.path.join(current_directory,dir1,new_file))
                        # print(f'rename {file} -> {new_file} ok')
                    except:
                        print(f'rename {file} -> {new_file} error')

            

# 扫描冲突的文件并自动删除
def handle_filename_conflicts(directory):
    files = os.listdir(directory)
    filename_counts = {}

    for file in files:
        if os.path.isfile(os.path.join(directory, file)):
            filename, _ = os.path.splitext(file)
            filename_lower = filename.lower()
            if filename_lower in filename_counts:
                old_path = os.path.join(directory, file)
                os.remove(old_path)
            else:
                filename_counts[filename_lower] = 1

# 统计每个子目录下的文件数量
def count_files():
    # 当前目录路径
    current_directory = os.path.join(os.getcwd(),'nuclei-templates')

    # 获取当前目录下的子目录列表
    subdirectories = [name for name in os.listdir(
        current_directory) if os.path.isdir(os.path.join(current_directory, name))]

    # 按templates type升序排序
    subdirectories = sorted(subdirectories)
    count = {}
    # 遍历子目录并统计文件数量
    for subdir in subdirectories:
        subdir_path = os.path.join(current_directory, subdir)
        handle_filename_conflicts(subdir_path)
        file_count = len(os.listdir(subdir_path))
        count[subdir] = file_count
    return count

# 获取新增加文件 PDD
def get_new_add_file():
    data = {}
    data_file = os.path.join(os.path.dirname(os.path.abspath(__file__)),'data1.json')
    if os.path.exists(data_file):
        try:
            data = json.loads(open(data_file,'r',encoding='utf8').read())
        except Exception as e:
            with open(data_file, 'w',encoding='utf-8') as f:
                json.dump(data, f,ensure_ascii=False,indent = 4)
    else:
        with open(data_file, 'w',encoding='utf-8') as f:
            json.dump(data, f,ensure_ascii=False,indent = 4)
    current_directory = os.path.join(os.getcwd(),'nuclei-templates')
    new_files = []
    for root, dirs, files in os.walk(current_directory):
        for file in files:
            if file not in data:
                data[file] = time.strftime("%Y-%m-%d %H:%M:%S")
                new_files.append(file)
    with open(data_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4) 
    return new_files

# 克隆GitHub项目到指定目录
async def clone_github_project(link, save_directory):
    # 提取项目名称
    project_name = link.split('/')[-1].replace('.git', '')

    # 构建保存路径
    save_directory = os.path.join(save_directory, f"{project_name}")
    os.makedirs(save_directory, exist_ok=True)

    # 构建克隆命令
    clone_command = f'git clone {link} {save_directory}'

    # 执行克隆命令
    process = await asyncio.create_subprocess_shell(clone_command)
    await process.wait()

# 克隆GitHub项目列表
async def clone_github_projects(links, temp_directory):
    tasks = []
    for link in links:
        # 创建每个克隆任务的协程对象
        task = clone_github_project(
            link, os.path.join(temp_directory, md5(link)))
        tasks.append(task)

    # 并发执行所有协程任务
    await asyncio.gather(*tasks)

# 主函数
async def main():

    # 输入文件路径
    file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),'links.csv')

    # 创建临时目录
    temp_directory = tempfile.mkdtemp()

    # 更新部分
    ## 读取GitHub项目链接
    links_1 = read_github_links(file_path)

    ## Search for GitHub project links
    links_2 = search_projects()

    ## Make a list of new GitHub project links
    links_3 = [link for link in links_2 if link not in links_1 and link !=
               'https://github.com/20142995/nuclei-templates']
    print(f'GitHub Projects: {len(links_1)} + {len(links_3)} ({len(links_2)})')

    ## Clone the GitHub project to the specified directory
    await clone_github_projects(links_1+links_3, temp_directory)

    ## Count .yaml files in the temporary directory
    count_1 = count_yaml_files(temp_directory, links_1+links_3)
    links_4 = [link for link in links_3 if count_1.get(link, 0) > 0]
    print(f'Valid GitHub Projects: {len(links_4)}')
    ## Append valid GitHub links
    append_github_links(file_path, links_4)

    ## Iterate through the .yaml files in the temporary directory and process them.
    process_yaml_files(temp_directory)
    ## Clean up files
    clear_file()

    ## Verify the YAML files in the temporary directory
    nuclei_validate(temp_directory)

    ## Clean up again
    clear_file()

    # Display section
    ## Count the number of files in each subdirectory
    count_new = count_files()
    count_new_list = sorted(count_new.items(), key=lambda x: x[0])
    count_old = {}
    data_file = os.path.join(os.path.dirname(os.path.abspath(__file__)),'data.json')
    if os.path.exists(data_file):
        try:
            count_old = json.loads(open(data_file,'r',encoding='utf8').read())
        except Exception as e:
            with open(data_file, 'w',encoding='utf-8') as f:
                json.dump(count_old, f,ensure_ascii=False,indent = 4)
    else:
        with open(data_file, 'w',encoding='utf-8') as f:
            json.dump(count_old, f,ensure_ascii=False,indent = 4)
    table_rows = []
    table_rows.append("## Classification Statistics")
    table_rows.append("| templates type | templates conut | \n| --- | --- |")
    date = time.strftime("%Y-%m-%d")
    ## Traverse subdirectories and count the number of files
    for subdir, file_count in count_new_list:
        table_row = f"| {subdir} | {file_count} |"
        table_rows.append(table_row)
    table_rows.append("## Changes in quantity in recent days")
    count_old[date] = sum([v for k,v in count_new_list])
    count_old_list = sorted(count_old.items(), key=lambda x: x[0])
    table_row = '|' + ' | '.join([k for k,v in count_old_list[-7:]]) + '|\n' + '|' + '--- | ---'*(len([k for k,v in count_old_list[-7:]])-1) + '|'
    table_rows.append(table_row)
    table_row = '|' + ' | '.join([str(v) for k,v in count_old_list[-7:]]) + '|'
    table_rows.append(table_row)
    table_rows.append("## Recently Added Files")
    new_files = get_new_add_file()
    table_rows.append("| templates name | \n| --- |")
    for filename in new_files:
        table_row = f"| {filename} |"
        table_rows.append(table_row)
    ## Write the results to the README.md file
    with open('README.md', 'w', encoding='utf8') as f:
        for row in table_rows:
            f.write(f"{row}\n")
    with open(data_file, 'w', encoding='utf-8') as f:
        json.dump(count_old, f, ensure_ascii=False, indent=4)
# Run the main function
if __name__ == '__main__':
    asyncio.run(main())
    
