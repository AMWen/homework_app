import csv
import sqlite3

import pandas as pd
import yaml
from flask import Flask, redirect, render_template, request, session
from wtforms import Form, StringField, validators

FILE_DIR = '.'
hw_configs = yaml.full_load(open(f'{FILE_DIR}/configs/hw.yml').read())

app = Flask(__name__)
app.secret_key = hw_configs['secret_key']
app.config['SESSION_TYPE'] = 'filesystem'

DB_NAME = f"{FILE_DIR}/hw_configs['DB_NAME']"
TABLE_NAME = hw_configs['TABLE_NAME']
CURRENT_HW = hw_configs['CURRENT_HW']
HW_CSV_FILE = hw_configs['HW_CSV_FILE']


def create_hw():
    conn = sqlite3.connect(DB_NAME)

    delete_query = f"""
            DROP TABLE IF EXISTS "{TABLE_NAME}";
            """
    query = f"""
            CREATE TABLE IF NOT EXISTS "{TABLE_NAME}" (
              id TEXT PRIMARY KEY,
              homework_name TEXT,
              student_name TEXT,
              question_number INTEGER,
              question_text TEXT,
              question_image_url TEXT,
              answer_options TEXT,
              correct_answer TEXT,
              answer_type TEXT,
              hint_1 TEXT,
              hint_2 TEXT,
              student_answer TEXT,
              num_attempts INTEGER DEFAULT 0,
              is_correct INTEGER DEFAULT 0
            );
            """

    conn.execute(delete_query)
    conn.execute(query)
    conn.close()


def insert_hw(HW_CSV_FILE):
    conn = sqlite3.connect(DB_NAME)
    file = open(f'{FILE_DIR}/{HW_CSV_FILE}')

    # SQL query to insert CSV data into the table
    contents = csv.reader(file)
    insert_records = f"""
                     INSERT INTO {TABLE_NAME}
                        (id, homework_name, student_name, question_number, question_text, question_image_url, answer_options, correct_answer, answer_type, hint_1, hint_2, student_answer)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                     """

    # Import the contents of the file
    conn.executemany(insert_records, contents)
    conn.commit()

    # Check contents of table
    select_all = f"SELECT * FROM {TABLE_NAME}"
    test = pd.read_sql_query(select_all, conn)
    print(test)

    conn.close()


def clean_answer(ans, answer_type):
    try:
        if answer_type == 'int':
            ans = int(ans)
        elif 'round' in answer_type:
            ans = round(ans, int(answer_type.split('round')[1]))
        elif answer_type == 'str':
            ans = ans.replace('\"', "")
    except ValueError:
        pass

    return ans


@app.route('/', methods=['GET', 'POST'])
@app.route('/index', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        print(dict(request.form))

    if not session.get('user'):
        # Ask user to select name since none selected yet
        if request.method != 'POST':
            return render_template("main.html", form=None, qbank=None, current_user="")

        else:
            # Set user to selected user
            session['user'] = dict(request.form)["button"]
            return redirect('/')

    else:
        # If user is reset, blank out name and allow another selection
        if request.method == 'POST' and dict(request.form).get("reset_button"):
            session['user'] = None
            return redirect('/')

        # Else, proceed to get questions for current user and homework assignment
        CURRENT_USER = session['user']

        conn = sqlite3.connect(DB_NAME)

        select_questions = f"""
                    SELECT * FROM {TABLE_NAME}
                    WHERE lower(homework_name) = lower('{CURRENT_HW}')
                    AND lower(student_name) = lower('{CURRENT_USER}')
                    ORDER BY question_number
                    """
        questions = pd.read_sql_query(select_questions, conn)

        conn.close()

        # Dictionary version of questions
        questions['question_number'] = questions['question_number'].astype(str)  # needs to be str for form
        qbank = questions.set_index('question_number').T.to_dict()

        class Questions(Form):
            pass

        qnums = []
        # Create a form input for each question; use iterrows instead of qbank to keep questions in numerical order
        for i, row in questions.iterrows():
            qnum = row['question_number']
            disabled = qbank[qnum]['num_attempts'] == 5 or (qbank[qnum]['is_correct'] == 1)
            setattr(
                Questions,
                qnum,
                StringField(
                    qnum,
                    [validators.Length(max=5)],
                    default=qbank[qnum]['student_answer'],
                    render_kw={'disabled': disabled},
                ),
            )
            qnums.append(qnum)

        form = Questions(request.form)

        # Compare responses in form to sql table to see if answer was changed, then check if solution is correct
        if request.method == 'POST' and dict(request.form).get("submit_button") and form.validate():
            for qnum in qnums:
                # Get all the fields
                qcurr_old = qbank[qnum]
                qcurr_new = form.data

                # Answers
                answer_type = qcurr_old['answer_type']
                answer_correct = qcurr_old['correct_answer']
                answer_old = qcurr_old['student_answer']
                num_attempts = qcurr_old['num_attempts']
                is_correct = qcurr_old['is_correct']
                answer_new = qcurr_new[qnum].strip().lower()

                # If the previous answer was wrong and there is an input
                if (not is_correct) and answer_new != '':

                    # Update answer type to match expected
                    answer_correct = clean_answer(answer_correct, answer_type)
                    answer_old = clean_answer(answer_old, answer_type)
                    answer_new = clean_answer(answer_new, answer_type)

                    # Check if answer changed since previous answer
                    if answer_new != answer_old:
                        # Increment number of attempts
                        num_attempts += 1

                        # Check if new answer is correct
                        if answer_new == answer_correct:
                            is_correct = 1
                        else:
                            is_correct = 0

                        print(qnum, num_attempts, answer_new, answer_correct, is_correct)

                        # Update SQL table (num_attempts, answer_new, is_correct)
                        update_records = f"""
                                          UPDATE {TABLE_NAME}
                                          SET num_attempts = {num_attempts}
                                          , student_answer = "{answer_new}"
                                          , is_correct = {is_correct}
                                          where id = "{qcurr_old['id']}";
                                          """

                        conn = sqlite3.connect(DB_NAME)
                        conn.execute(update_records)
                        conn.commit()
                        conn.close()

            return redirect('/')

    return render_template("main.html", form=form, qbank=qbank, current_user=CURRENT_USER)


if __name__ == '__main__':
    app.run(debug=True)
