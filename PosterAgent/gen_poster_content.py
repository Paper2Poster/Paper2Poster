import tempfile
import shutil
from dotenv import load_dotenv
from utils.src.utils import get_json_from_response
from concurrent.futures import ThreadPoolExecutor, as_completed
import json

from camel.models import ModelFactory
from PosterAgent.gen_pptx_code import generate_poster_code
from camel.agents import ChatAgent
from camel.messages import BaseMessage
from utils.src.utils import ppt_to_images
from PIL import Image

from utils.wei_utils import *

from utils.pptx_utils import *
from utils.critic_utils import *
import yaml
from jinja2 import Environment, StrictUndefined
import argparse

load_dotenv()
MAX_ATTEMPT = 10

def gen_content_process_section(
    section_name, 
    outline, 
    raw_content, 
    raw_outline, 
    template, 
    create_actor_agent, 
    MAX_ATTEMPT
):
    """
    Process a single section in its own thread or process.
    Returns (section_name, result_json, total_input_token, total_output_token).
    """
    # Create a fresh ActorAgent instance for each parallel call
    actor_agent = create_actor_agent()
    
    section_outline = ''
    num_attempts = 0
    total_input_token = 0
    total_output_token = 0
    result_json = None
    
    while True:
        print(f"[Thread] Generating content for section: {section_name}")
        
        if len(section_outline) == 0:
            # Initialize the section outline
            section_outline = json.dumps(outline[section_name], indent=4)
        
        # Render prompt using Jinja template
        jinja_args = {
            'json_outline': section_outline,
            'json_content': raw_content,
        }
        prompt = template.render(**jinja_args)
        
        # Step the actor_agent and track tokens
        response = actor_agent.step(prompt)
        input_token, output_token = account_token(response)
        total_input_token += input_token
        total_output_token += output_token
        
        # Parse JSON and possibly adjust text length
        result_json = get_json_from_response(response.msgs[0].content)
        new_section_outline, suggested = generate_length_suggestions(
            result_json,
            json.dumps(outline[section_name]),
            raw_outline[section_name]
        )
        section_outline = json.dumps(new_section_outline, indent=4)
        
        if not suggested:
            # No more adjustments needed
            break
        
        print(f"[Thread] Adjusting text length for section: {section_name}...")
        
        num_attempts += 1
        if num_attempts >= MAX_ATTEMPT:
            break
    
    return section_name, result_json, total_input_token, total_output_token


def gen_content_parallel_process_sections(
    sections,
    outline,
    raw_content,
    raw_outline,
    template,
    create_actor_agent,
    MAX_ATTEMPT=3
):
    """
    Parallelize the section processing using ThreadPoolExecutor.
    """
    poster_content = {}
    total_input_token = 0
    total_output_token = 0

    # Create a pool of worker threads (or processes)
    with ThreadPoolExecutor() as executor:
        futures = []
        
        # Submit each section to be processed in parallel
        for section_name in sections:
            futures.append(
                executor.submit(
                    gen_content_process_section, 
                    section_name,
                    outline,
                    raw_content,
                    raw_outline,
                    template,
                    create_actor_agent,
                    MAX_ATTEMPT
                )
            )
        
        # Collect results as they complete
        for future in as_completed(futures):
            section_name, result_json, sec_input_token, sec_output_token = future.result()
            poster_content[section_name] = result_json
            total_input_token += sec_input_token
            total_output_token += sec_output_token
    
    return poster_content, total_input_token, total_output_token

def render_textbox(text_arrangement, textbox_content, tmp_dir):
    arrangement = copy.deepcopy(text_arrangement)
    arrangement['x'] = 1
    arrangement['y'] = 1

    poster_code = generate_poster_code(
        [],
        [arrangement],
        [],
        presentation_object_name='poster_presentation',
        slide_object_name='poster_slide',
        utils_functions=utils_functions,
        slide_width=text_arrangement['width'] + 3,
        slide_height=text_arrangement['height'] + 3,
        img_path='placeholder.jpg',
        save_path=f'{tmp_dir}/poster.pptx',
        visible=True,
        content=textbox_content,
        check_overflow=True,
        tmp_dir=tmp_dir,
    )

    output, err = run_code(poster_code)
    ppt_to_images(f'{tmp_dir}/poster.pptx', tmp_dir, output_type='jpg')
    img = Image.open(f'{tmp_dir}/poster.jpg')

    return img

def gen_poster_title_content(args, actor_config):
    total_input_token, total_output_token = 0, 0
    raw_content = json.load(open(f'contents/<{args.model_name_t}_{args.model_name_v}>_{args.poster_name}_raw_content.json', 'r'))
    actor_agent_name = 'poster_title_agent'

    title_string = raw_content['meta']

    with open(f'utils/prompt_templates/{actor_agent_name}.yaml', "r") as f:
        content_config = yaml.safe_load(f)
    jinja_env = Environment(undefined=StrictUndefined)
    template = jinja_env.from_string(content_config["template"])

    if args.model_name_t == 'vllm_qwen':
        actor_model = ModelFactory.create(
            model_platform=actor_config['model_platform'],
            model_type=actor_config['model_type'],
            model_config_dict=actor_config['model_config'],
            url=actor_config['url'],
        )
    else:
        actor_model = ModelFactory.create(
            model_platform=actor_config['model_platform'],
            model_type=actor_config['model_type'],
            model_config_dict=actor_config['model_config']
        )

    actor_sys_msg = content_config['system_prompt']
    actor_agent = ChatAgent(
        system_message=actor_sys_msg,
        model=actor_model,
        message_window_size=30
    )

    jinja_args = {
        'title_string': title_string,
        'title_font_size': getattr(args, 'poster_title_font_size', None) or getattr(args, 'title_font_size', None),
        'author_font_size': getattr(args, 'poster_author_font_size', None) or getattr(args, 'author_font_size', None),
    }
    prompt = template.render(**jinja_args)
    # Step the actor_agent and track tokens
    actor_agent.reset()
    response = actor_agent.step(prompt)
    input_token, output_token = account_token(response)
    total_input_token += input_token
    total_output_token += output_token
    result_json = get_json_from_response(response.msgs[0].content)

    return result_json, total_input_token, total_output_token

def gen_bullet_point_content(args, actor_config, critic_config, agent_modify=True, tmp_dir='tmp'):
    import json, yaml, copy, threading
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from PIL import Image
    from jinja2 import Environment, StrictUndefined

    # ----------------------- Load data & configs -----------------------
    total_input_token_t = total_output_token_t = 0
    total_input_token_v = total_output_token_v = 0

    raw_content = json.load(open(f'contents/<{args.model_name_t}_{args.model_name_v}>_{args.poster_name}_raw_content.json', 'r'))
    with open(f'tree_splits/<{args.model_name_t}_{args.model_name_v}>_{args.poster_name}_tree_split_{args.index}.json', 'r') as f:
        tree_split_results = json.load(f)

    panels = tree_split_results['panels']
    text_arrangement_list = tree_split_results['text_arrangement_inches']

    actor_agent_name = 'bullet_point_agent'
    if args.model_name_v == 'vllm_qwen_vl':
        critic_agent_name = 'critic_overlap_agent_v3_short'
    else:
        critic_agent_name = 'critic_overlap_agent_v3'

    with open(f"utils/prompt_templates/{actor_agent_name}.yaml", "r") as f:
        content_config = yaml.safe_load(f)
    with open(f"utils/prompt_templates/{critic_agent_name}.yaml", "r") as f:
        critic_content_config = yaml.safe_load(f)

    jinja_env = Environment(undefined=StrictUndefined)
    template = jinja_env.from_string(content_config["template"])
    critic_template = jinja_env.from_string(critic_content_config["template"])

    # Preload images once (each worker can reopen if needed, or just pass paths)
    neg_img_path = 'assets/overflow_example_v2/neg.jpg'
    pos_img_path = 'assets/overflow_example_v2/pos.jpg'

    # Group text arrangements by panel_id for O(1) lookup in workers
    from collections import defaultdict
    textboxes_by_panel = defaultdict(list)
    for ta in text_arrangement_list:
        textboxes_by_panel[ta['panel_id']].append(ta)
    # Ensure deterministic order inside each panel
    for k in textboxes_by_panel:
        textboxes_by_panel[k] = sorted(textboxes_by_panel[k], key=lambda x: x.get('textbox_id', 0))

    # ----------------------- Worker (defined INSIDE main fn) -----------------------
    def _process_section(i):
        """
        Returns:
          (i, result_json, t_in, t_out, v_in, v_out)
        """
        local_t_in = local_t_out = 0
        local_v_in = local_v_out = 0

        arrangement = panels[i]
        num_textboxes = 2 if arrangement.get('gp', 0) > 0 else 1

        local_tmp_dir = tempfile.mkdtemp(prefix=f"sec_{i}_", dir=tmp_dir)

        jinja_args = {
            'summary_of_section': raw_content['sections'][i]['content'],
            'number_of_textboxes': num_textboxes,
            'section_title': raw_content['sections'][i]['title'],
            'bullet_font_size': args.bullet_font_size,
            'section_title_font_size': args.section_title_font_size,
        }

        target_textboxes = textboxes_by_panel[i][1:]  # skip first (section title)
        total_expected_length = sum(tb['num_chars'] for tb in target_textboxes)

        # Create fresh models & agents per thread for safety
        if args.model_name_t.startswith('vllm_qwen'):
            actor_model = ModelFactory.create(
                model_platform=actor_config['model_platform'],
                model_type=actor_config['model_type'],
                model_config_dict=actor_config['model_config'],
                url=actor_config['url'],
            )
        else:
            actor_model = ModelFactory.create(
                model_platform=actor_config['model_platform'],
                model_type=actor_config['model_type'],
                model_config_dict=actor_config['model_config']
            )
        if args.model_name_v.startswith('vllm_qwen'):
            critic_model = ModelFactory.create(
                model_platform=critic_config['model_platform'],
                model_type=critic_config['model_type'],
                model_config_dict=critic_config['model_config'],
                url=critic_config['url'],
            )
        else:
            critic_model = ModelFactory.create(
                model_platform=critic_config['model_platform'],
                model_type=critic_config['model_type'],
                model_config_dict=critic_config['model_config']
            )

        actor_agent = ChatAgent(system_message=content_config['system_prompt'], model=actor_model, message_window_size=30)
        critic_agent = ChatAgent(system_message=critic_content_config['system_prompt'], model=critic_model, message_window_size=10)

        prompt = template.render(**jinja_args)
        actor_agent.reset()
        response = actor_agent.step(prompt)
        t_in, t_out = account_token(response)
        local_t_in += t_in
        local_t_out += t_out

        result_json = get_json_from_response(response.msgs[0].content)

        max_attempts = 5
        num_attempts = 0
        old_result_json = copy.deepcopy(result_json)

        # Length control loop
        while args.estimate_chars:
            num_attempts += 1
            if num_attempts > max_attempts:
                result_json = old_result_json
                break
            try:
                total_bullet_length = 0
                for j in range(num_textboxes):
                    bullet_content_key = f'textbox{j + 1}'
                    total_bullet_length += compute_bullet_length(result_json[bullet_content_key])
            except Exception:
                result_json = old_result_json
                break

            if total_bullet_length > total_expected_length:
                percentage_to_shrink = int((total_bullet_length - total_expected_length) / total_bullet_length * 100)
                percentage_to_shrink = min(90, percentage_to_shrink + 10)
                old_result_json = copy.deepcopy(result_json)
                response = actor_agent.step('Too long, please shorten the bullet points by ' + str(percentage_to_shrink) + '%.')
                t_in, t_out = account_token(response)
                local_t_in += t_in
                local_t_out += t_out
                result_json = get_json_from_response(response.msgs[0].content)
            else:
                break

        critic_prompt = critic_template.render()
        bullet_contents = ['textbox1'] + (['textbox2'] if num_textboxes == 2 else [])

        # Visual overflow/blank detection & correction
        for j, text_arrangement in enumerate(target_textboxes[:num_textboxes]):
            bullet_content = bullet_contents[j]
            curr_round = 0
            while True:
                if args.ablation_no_commenter:
                    break
                curr_round += 1
                img = render_textbox(text_arrangement, result_json[bullet_content], local_tmp_dir)
                if args.model_name_v.startswith('vllm_qwen') or args.ablation_no_example:
                    critic_msg = BaseMessage.make_user_message(
                        role_name="User",
                        content=critic_prompt,
                        image_list=[img],
                    )
                else:
                    critic_msg = BaseMessage.make_user_message(
                        role_name="User",
                        content=critic_prompt,
                        image_list=[Image.open(neg_img_path), Image.open(pos_img_path), img],
                    )

                critic_agent.reset()
                response = critic_agent.step(critic_msg)
                v_in, v_out = account_token(response)
                local_v_in += v_in
                local_v_out += v_out

                decision = response.msgs[0].content.lower()
                if decision in ['1', '1.', '"1"', "'1'"]:
                    if curr_round > 10:
                        print(f'Section {i}: Too many rounds of modification, breaking...')
                        break
                    if agent_modify:
                        print(f'Section {i}: Text overflow detected, modifying...')
                        modify_message = f'{bullet_content} is too long, please shorten that part, other content should stay the same. Return the entire modified JSON.'
                        response = actor_agent.step(modify_message)
                        t_in, t_out = account_token(response)
                        local_t_in += t_in
                        local_t_out += t_out
                        result_json = get_json_from_response(response.msgs[0].content)
                    else:
                        # naive truncate
                        result_json[bullet_content] = result_json[bullet_content][:-1]
                    continue
                elif decision in ['2', '2.', '"2"', "'2'"]:
                    if args.no_blank_detection:
                        print(f'Section {i}: No blank space detection, skipping...')
                        break
                    if curr_round > 10:
                        print(f'Section {i}: Too many rounds of modification, breaking...')
                        break
                    print(f'Section {i}: Too much blank space detected, modifying...')
                    modify_message = f'{bullet_content} is too short, please add one more bullet point, other content should stay the same. Return the entire modified JSON.'
                    response = actor_agent.step(modify_message)
                    t_in, t_out = account_token(response)
                    local_t_in += t_in
                    local_t_out += t_out
                    result_json = get_json_from_response(response.msgs[0].content)
                else:
                    break

        # Clean up temp dir
        if local_tmp_dir:
            try:
                print(f'Section {i}: Cleaning up temp dir {local_tmp_dir}')
                shutil.rmtree(local_tmp_dir)
            except Exception as e:
                print(f"Error cleaning up temp dir {local_tmp_dir}: {e}")
        return i, result_json, local_t_in, local_t_out, local_v_in, local_v_out

    # ----------------------- Parallel execution -----------------------
    max_workers = getattr(args, 'max_workers', 4)
    results = {}
    lock = threading.Lock()

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {
            ex.submit(_process_section, i): i
            for i in range(1, len(raw_content['sections']))
        }
        for fut in as_completed(futures):
            i, rjson, t_in, t_out, v_in, v_out = fut.result()
            with lock:
                results[i] = rjson
                total_input_token_t += t_in
                total_output_token_t += t_out
                total_input_token_v += v_in
                total_output_token_v += v_out

    # ----------------------- Title generation (sequential) -----------------------
    title_json, title_input_token, title_output_token = gen_poster_title_content(args, actor_config)
    total_input_token_t += title_input_token
    total_output_token_t += title_output_token

    # ----------------------- Assemble & save -----------------------
    bullet_point_content = [title_json]
    for idx in range(1, len(raw_content['sections'])):
        bullet_point_content.append(results[idx])

    json.dump(
        bullet_point_content,
        open(f'contents/<{args.model_name_t}_{args.model_name_v}>_{args.poster_name}_bullet_point_content_{args.index}.json', 'w'),
        indent=2
    )

    return total_input_token_t, total_output_token_t, total_input_token_v, total_output_token_v

def gen_poster_content(args, actor_config):
    total_input_token, total_output_token = 0, 0
    raw_content = json.load(open(f'contents/{args.model_name}_{args.poster_name}_raw_content.json', 'r'))
    agent_name = 'poster_content_agent'

    with open(f"utils/prompt_templates/{agent_name}.yaml", "r") as f:
        content_config = yaml.safe_load(f)

    actor_model = ModelFactory.create(
        model_platform=actor_config['model_platform'],
        model_type=actor_config['model_type'],
        model_config_dict=actor_config['model_config']
    )

    actor_sys_msg = content_config['system_prompt']

    def create_actor_agent():
        actor_agent = ChatAgent(
            system_message=actor_sys_msg,
            model=actor_model,
            message_window_size=10
        )
        return actor_agent

    outline = json.load(open(f'outlines/{args.model_name}_{args.poster_name}_outline_{args.index}.json', 'r'))
    raw_outline = json.loads(json.dumps(outline))
    outline_estimate_num_chars(outline)
    outline = remove_hierarchy_and_id(outline)

    sections = list(outline.keys())
    sections = [s for s in sections if s != 'meta']

    jinja_env = Environment(undefined=StrictUndefined)

    template = jinja_env.from_string(content_config["template"])

    poster_content = {}

    poster_content, total_input_token, total_output_token = gen_content_parallel_process_sections(
        sections, 
        outline, 
        raw_content, 
        raw_outline, 
        template, 
        create_actor_agent, 
        MAX_ATTEMPT=5
    )

    json.dump(poster_content, open(f'contents/{args.model_name}_{args.poster_name}_poster_content_{args.index}.json', 'w'), indent=2)
    return total_input_token, total_output_token

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--poster_name', type=str, default=None)
    parser.add_argument('--model_name', type=str, default='gemini-2.5-pro')
    parser.add_argument('--poster_path', type=str, required=True)
    parser.add_argument('--index', type=int, default=0)
    parser.add_argument('--max_retry', type=int, default=3)
    args = parser.parse_args()

    actor_config = get_agent_config(args.model_name)
    if args.poster_name is None:
        args.poster_name = args.poster_path.split('/')[-1].replace('.pdf', '').replace(' ', '_')

    input_token, output_token = gen_poster_content(args, actor_config)

    print(f'Token consumption: {input_token} -> {output_token}')
