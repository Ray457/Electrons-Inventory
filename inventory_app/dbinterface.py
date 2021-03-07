import sqlite3
import traceback


class ItemRecord:
    """
    Corresponds to a record in the database. Useful for passing information around
    """
    def __init__(self,
                 has_dmtx,
                 loc: str = "",
                 qty: int = 0,
                 name: str = "",
                 pn: str = "",
                 mfg_pn: str = "",
                 cat: str = "",
                 desc: str = "",
                 supplier: str = "",
                 manufacturer: str = "",
                 proj: str = "",
                 cust_ref: str = "",
                 comment: str = "",
                 dmtx: bytes = b""
                 ):
        self.name: str = name
        self.supplier_pn: str = pn
        self.manufacturer_pn: str = mfg_pn
        self.location: str = loc
        self.quantity: int = qty
        self.category: str = cat
        self.description: str = desc
        self.supplier: str = supplier
        self.manufacturer: str = manufacturer
        self.used_by_proj: str = proj
        self.customer_ref: str = cust_ref
        self.comment: str = comment
        self.dmtx: bytes = dmtx

        # flag to indicate if the item is supposed to have the data matrix code.
        # If it's true and dmtx is empty, the object is not ready to be stored into the DB
        self.has_dmtx = has_dmtx

    @classmethod
    def from_db_row(cls, db_row: tuple):
        dmtx = db_row[12]
        if (dmtx is not None) and (dmtx != b""):
            has_dmtx = True
        else:
            has_dmtx = False

        return cls(
            has_dmtx=has_dmtx,
            name=db_row[0],
            pn=db_row[1],
            mfg_pn=db_row[2],
            loc=db_row[3],
            qty=db_row[4],
            cat=db_row[5],
            desc=db_row[6],
            supplier=db_row[7],
            manufacturer=db_row[8],
            proj=db_row[9],
            cust_ref=db_row[10],
            comment=db_row[11],
            dmtx=db_row[12]
        )


def db_rows_to_itemrecords(db_rows: list):
    results = []
    for row in db_rows:
        results += [ItemRecord.from_db_row(db_row=row)]
    return results


class DbInterface:
    """
    Interface to the SQLite database. Corresponds to the model in MVC
    """
    def __init__(self):
        self.db_conn = None  # SQLite connection object
        self.db_cur = None  # SQLite cursor object

    def connect(self, filename: str = "AppData/inventory.db") -> None:
        """
        Connect to a SQLite file at the same directory. If there's no table with the matching name, create one.
        :param filename: file name for the database file
        :return: None
        """
        self.db_conn = sqlite3.connect(filename)
        self.db_cur = self.db_conn.cursor()

        # Create the database if not present
        self.db_cur.execute('CREATE TABLE IF NOT EXISTS "FSAE47 Inventory" ('
                            '"Name"	TEXT,'
                            '"Supplier P/N"	TEXT,'
                            '"Manufacturer P/N"	TEXT,'
                            '"Location"	TEXT NOT NULL,'
                            '"Quantity"	INTEGER NOT NULL CHECK("Quantity">=0),'
                            '"Category"	TEXT,'
                            '"Description"	TEXT,'
                            '"Supplier"	TEXT,'
                            '"Manufacturer"	TEXT,'
                            '"Used by Project"	TEXT,'
                            '"Customer Ref"	TEXT,'
                            '"Comment"	TEXT,'
                            '"Dmtx Raw"	BLOB NOT NULL,'
                            # Making the data matrix the primary key to speed up searching by code
                            'PRIMARY KEY("Dmtx Raw"));')

        self.db_cur.execute('CREATE TABLE IF NOT EXISTS "DB_CFG" ('
                            '"key" TEXT NOT NULL PRIMARY KEY UNIQUE,'
                            '"value" TEXT'
                            ');')

        # test if the config is there
        self.db_cur.execute('SELECT * FROM "DB_CFG" WHERE "key"="dmtx_ser"')
        if len(self.db_cur.fetchall()) == 0:  # config not present
            self.db_cur.execute('INSERT INTO "DB_CFG" VALUES(:key, :value)',
                                {
                                    "key": "dmtx_ser",
                                    "value": "0"
                                })  # a number in place of the data matrix code if that's not present
        self.db_conn.commit()

    def add_component(self, item: ItemRecord) -> None:
        if item.dmtx is None or item.dmtx == b"":  # assign a number to ensure uniqueness
            if item.has_dmtx:
                print("ItemRecord object not ready to store! Abort saving...")
                return
            self.db_cur.execute('SELECT * FROM "DB_CFG" WHERE "key"="dmtx_ser"')
            res = self.db_cur.fetchall()  # returns a list
            if len(res) == 1:
                res = res[0]  # take the first (and only) row in the querying result
                dmtx_ser_int = int(res[1])  # a row is in tuple
                dmtx_ser_str = "{:07d}".format(dmtx_ser_int)
                item.dmtx = bytes(dmtx_ser_str, "ascii")

                # write the incremented value back into the DB
                dmtx_ser_int += 1
                self.db_cur.execute('UPDATE "DB_CFG"'
                                    'SET "value"="{}"'
                                    'WHERE "key"="dmtx_ser"'
                                    ''.format(dmtx_ser_int))
            else:
                print("Error in the config table! (Multiple dmtx_ser)")
                print("Record NOT saved.")
                return
        self.db_cur.execute('INSERT INTO "FSAE47 Inventory" VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                            (item.name,
                             item.supplier_pn,
                             item.manufacturer_pn,
                             item.location,
                             item.quantity,
                             item.category,
                             item.description,
                             item.supplier,
                             item.manufacturer,
                             item.used_by_proj,
                             item.customer_ref,
                             item.comment,
                             item.dmtx))
        self.db_conn.commit()

    def update_component(self, item: ItemRecord):
        """
        Updates an item in the database. Assumes that the item exists in the records
        :param item: the ItemRecord object to update
        :return:
        """
        update_sql = 'UPDATE "FSAE47 Inventory" ' \
                     'SET ' \
                     '"Name" = ?, ' \
                     '"Supplier P/N" = ?, ' \
                     '"Manufacturer P/N" = ?, ' \
                     '"Location" = ?, ' \
                     '"Quantity" = ?, ' \
                     '"Category" = ?, ' \
                     '"Description" = ?, ' \
                     '"Supplier" = ?, ' \
                     '"Manufacturer" = ?, ' \
                     '"Used by Project" = ?, ' \
                     '"Customer Ref" = ?, ' \
                     '"Comment" = ?' \
                     'WHERE ' \
                     '"Dmtx Raw" = ?'
        self.db_cur.execute(update_sql,
                            (item.name,
                             item.supplier_pn,
                             item.manufacturer_pn,
                             item.location,
                             item.quantity,
                             item.category,
                             item.description,
                             item.supplier,
                             item.manufacturer,
                             item.used_by_proj,
                             item.customer_ref,
                             item.comment,
                             item.dmtx
                             )
                            )
        self.db_conn.commit()

    def basic_search(self, keyword: str) -> list:
        """
        searches the given keyword in every column of the database
        :return: list of results, as ItemRecord objects
        """
        search_limit = 200
        basic_search_sql = 'SELECT * FROM "FSAE47 Inventory" WHERE' \
                           '(' \
                           '"Name" LIKE {0} ESCAPE {1}' \
                           'OR "Supplier P/N" LIKE {0} ESCAPE {1}' \
                           'OR "Manufacturer P/N" LIKE {0} ESCAPE {1}' \
                           'OR "Location" LIKE {0} ESCAPE {1}' \
                           'OR "Quantity" LIKE {0} ESCAPE {1}' \
                           'OR "Category" LIKE {0} ESCAPE {1}' \
                           'OR "Description" LIKE {0} ESCAPE {1}' \
                           'OR "Supplier" LIKE {0} ESCAPE {1}' \
                           'OR "Manufacturer" LIKE {0} ESCAPE {1}' \
                           'OR "Used by Project" LIKE {0} ESCAPE {1}' \
                           'OR "Customer Ref" LIKE {0} ESCAPE {1}' \
                           'OR "Comment" LIKE {0} ESCAPE {1}' \
                           ')' \
                           'LIMIT {2}'
        basic_search_sql = basic_search_sql.format(":kw", "'\\'", search_limit)  # add in the LIKE and ESCAPE keyword
        self.db_cur.execute(basic_search_sql, {"kw": "%"+keyword+"%"})
        rows = self.db_cur.fetchall()
        return db_rows_to_itemrecords(db_rows=rows)

    def advanced_search(self, cols: list, inputs: list, logics: list) -> list:
        """
        Searches the database based on field, keyword and logic between them.
        Hard-coded to work with up to 3 inputs and 2 logic choices.
        Inputs are assumed to be not empty.
        :param cols: list of the column/field names
        :param inputs: list of search keywords
        :param logics: list of logic choices ("AND"/"OR") between the search fields
        :return: list of results, as ItemRecord objects
        """
        search_limit = 200
        if len(cols) == 1:
            advanced_search_sql = 'SELECT * FROM "FSAE47 Inventory" WHERE' \
                                  '"{1}" LIKE :kw ESCAPE {0}' \
                                  'LIMIT {2}'.format( "'\\'", cols[0], search_limit)
            params = {
                "kw": "%"+inputs[0]+"%"
            }
            self.db_cur.execute(advanced_search_sql, params)
            rows = self.db_cur.fetchall()
            return db_rows_to_itemrecords(db_rows=rows)
        if len(cols) == 2:
            advanced_search_sql = 'SELECT * FROM "FSAE47 Inventory" WHERE' \
                                  '(' \
                                  '"{1}" LIKE :kw1 ESCAPE {0}' \
                                  '{2} "{3}" LIKE :kw2 ESCAPE {0}' \
                                  ')' \
                                  'LIMIT {4}'.format("'\\'", cols[0], logics[0], cols[1], search_limit)
            params = {
                "kw1": "%"+inputs[0]+"%",
                "kw2": "%"+inputs[1]+"%"
            }
            self.db_cur.execute(advanced_search_sql, params)
            rows = self.db_cur.fetchall()
            return db_rows_to_itemrecords(db_rows=rows)
        if len(cols) == 3:
            advanced_search_sql = 'SELECT * FROM "FSAE47 Inventory" WHERE' \
                                  '(' \
                                  '"{1}" LIKE :kw1 ESCAPE {0}' \
                                  '{2} "{3}" LIKE :kw2 ESCAPE {0}' \
                                  '{4} "{5}" LIKE :kw3 ESCAPE {0}' \
                                  ')' \
                                  'LIMIT {6}'.format("'\\'", cols[0], logics[0], cols[1], logics[1], cols[2],
                                                     search_limit)
            params = {
                "kw1": "%"+inputs[0]+"%",
                "kw2": "%"+inputs[1]+"%",
                "kw3": "%"+inputs[2]+"%"
            }
            self.db_cur.execute(advanced_search_sql, params)
            rows = self.db_cur.fetchall()
            return db_rows_to_itemrecords(db_rows=rows)

    def get_item_by_code(self, dmtx: bytes):
        get_sql = 'SELECT * FROM "FSAE47 Inventory" WHERE' \
              '"Dmtx Raw" = ?' \
              'LIMIT 1'
        self.db_cur.execute(get_sql, (dmtx, ))
        rows = self.db_cur.fetchall()
        if len(rows) > 0:
            return ItemRecord.from_db_row(db_row=rows[0])
        else:
            return None

    def remove_component(self, dmtx: bytes) -> bool:
        """
        Remove an item from the database based on the given data matrix code.
        :param dmtx:
        :return: True if the deletion was successful, False otherwise
        """
        # check item presence
        res = self.get_item_by_code(dmtx=dmtx)
        if res is None:  # item not present
            return False

        del_sql = 'DELETE FROM "FSAE47 Inventory" ' \
                  'WHERE "Dmtx Raw" = ?'

        self.db_cur.execute(del_sql, (dmtx, ))
        self.db_conn.commit()  # save changes
        return True

    def get_all(self):
        """
        Gets some entries from the DB for display
        :return:
        """
        self.db_cur.execute('SELECT * '
                            'FROM "FSAE47 Inventory" '
                            'ORDER BY "_rowid_" DESC '
                            'LIMIT 50')
        rows = self.db_cur.fetchall()
        return db_rows_to_itemrecords(db_rows=rows)

    def close(self) -> None:
        """
        Closes the SQLite connection
        :return:
        """
        self.db_conn.close()
