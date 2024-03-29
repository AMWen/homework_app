import csv
import sqlite3
from datetime import datetime, timedelta, timezone

import pandas as pd
import yaml
from flask import Flask, redirect, render_template, request, session
from wtforms import Form, StringField, validators

FILE_DIR = '.'
hw_configs = yaml.full_load(open(f'{FILE_DIR}/configs/hw.yml').read())

app = Flask(__name__)
app.secret_key = hw_configs['secret_key']
app.config['SESSION_TYPE'] = 'filesystem'

DB_NAME = f"{FILE_DIR}/{hw_configs['DB_NAME']}"
TABLE_NAME = hw_configs['TABLE_NAME']
HW_CSV_FILE = hw_configs['HW_CSV_FILE']
ALL_HW = hw_configs['HW']


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


def insert_hw(hw_csv_file):
    conn = sqlite3.connect(DB_NAME)
    file = open(f'{FILE_DIR}/{hw_csv_file}')

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


def select_questions(current_user, current_hw):
    conn = sqlite3.connect(DB_NAME)
    select_query = f"""
                    SELECT * FROM {TABLE_NAME}
                    WHERE lower(homework_name) = lower('{current_hw}')
                    AND lower(student_name) = lower('{current_user}')
                    ORDER BY question_number
                    """
    questions = pd.read_sql_query(select_query, conn)
    conn.close()

    return questions


def delete_questions(current_hw, current_user=None):
    conn = sqlite3.connect(DB_NAME)
    delete_query = f"""
                    DELETE FROM {TABLE_NAME}
                    WHERE lower(homework_name) = lower('{current_hw}')
                    """
    if current_user:
        delete_query += f"AND lower(student_name) = lower('{current_user}')"
    conn.execute(delete_query)
    conn.commit()
    conn.close()


def clean_answer(ans, answer_type):
    ans = ans.strip().lower()
    try:
        if answer_type == 'int':
            ans = int(ans.replace('%', "").replace('$', ""))
        elif 'round' in answer_type:
            ans = round(float(ans), int(answer_type.split('round')[1]))
        elif answer_type == 'str':
            ans = ans.replace('\"', "")
        elif answer_type == 'str_cap':
            ans = ans.replace('\"', "").upper()
    except ValueError:
        pass

    return ans


@app.route('/', methods=['GET', 'POST'])
@app.route('/index', methods=['GET', 'POST'])
def index():
    # Update to most recent homework assignment
    current_datetime = datetime.now(timezone.utc)
    CURRENT_HW = ALL_HW[0]
    for hw in ALL_HW[1:]:
        HW_MONTH, HW_DATE = int(hw.split('-')[0][:2]), int(hw.split('-')[0][2:])
        print(current_datetime, datetime(2023, HW_MONTH, HW_DATE, 22, 0, 0, tzinfo=timezone.utc))
        if current_datetime > datetime(2023, HW_MONTH, HW_DATE, 0, 0, 0, tzinfo=timezone.utc) - timedelta(
            1
        ):  # for testing
            CURRENT_HW = hw

    if request.method == 'POST':
        print(dict(request.form))

    if not session.get('user'):
        # Ask user to select name since none selected yet
        if request.method != 'POST':
            return render_template(
                "main.html", form=None, qbank=None, current_user="", current_correct=None, total_qns=None
            )

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

        try:
            questions = select_questions(CURRENT_USER, CURRENT_HW)

            if len(questions) > 0 or CURRENT_USER == 'Amy':
                print('success getting questions')
            else:
                raise ValueError("There are not any questions available")

        except ValueError:
            try:
                insert_hw(HW_CSV_FILE)
                print('Success inserting new questions')
            except sqlite3.DatabaseError:
                pass

            questions = select_questions(CURRENT_USER, CURRENT_HW)
            print('Tried getting questions a second time')

        except pd.errors.DatabaseError:
            create_hw()
            insert_hw(HW_CSV_FILE)
            questions = select_questions(CURRENT_USER, CURRENT_HW)
            print('Reset database and tried getting questions a second time')

        # Dictionary version of questions
        questions['question_number'] = questions['question_number'].astype(str)  # needs to be str for form
        qbank = questions.set_index('question_number').T.to_dict()

        CURRENT_CORRECT = questions.is_correct.sum()
        TOTAL_QNS = questions.query(
            'answer_type != "none"'
        ).question_number.count()  # ignore questions that can't be submitted

        print(qbank)

        class Questions(Form):
            pass

        qnums = []
        # Create a form input for each question; use iterrows instead of qbank to keep questions in numerical order
        for i, row in questions.iterrows():
            qnum = row['question_number']
            disabled = (qbank[qnum]['num_attempts'] == 5 or (qbank[qnum]['is_correct'] == 1)) and (
                CURRENT_USER != 'Amy'
            )
            setattr(
                Questions,
                qnum,
                StringField(
                    qnum,
                    [validators.Length(max=7)],
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
                answer_new = qcurr_new[qnum]

                # If the previous answer was wrong and there is an input
                if ((not is_correct) or (CURRENT_USER == 'Amy')) and answer_new != '':

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

    return render_template(
        "main.html",
        form=form,
        qbank=qbank,
        current_user=CURRENT_USER,
        current_correct=CURRENT_CORRECT,
        total_qns=TOTAL_QNS,
    )


if __name__ == '__main__':
    app.run(debug=True)
