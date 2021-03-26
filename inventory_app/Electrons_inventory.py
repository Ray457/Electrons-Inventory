# control and logging
import sys
import logging
from datetime import datetime
import platform

# application specific libraries
from pylibdmtx.pylibdmtx import decode
from cv2 import cv2
import numpy as np

# GUI
import wx
from Inventory_GUI import MainFrame
from custom_dialogs import ViewResultDialog, CheckoutDialog

# database interface
from dbinterface import ItemRecord
from dbinterface import DbInterface

# Digi-Key API interface
from dkinterface import DKAPIInterface

if platform.system() == "Windows":
    import winsound  # Windows only!

FRAME_RATE = 15  # for camera frames


class InventoryFrame(MainFrame):
    """
    The GUI frame object, which also acts as the controller in the MVC pattern
    """
    def __init__(self, *args, **kwargs):
        MainFrame.__init__(self, *args, **kwargs)  # invoke constructor of the parent class

        # camera objects
        self.camera_cap = None
        self.camera_on = False
        self.camera_frame = None
        self.frame_height = None
        self.frame_width = None
        self.frame_bmp = None
        self.camera_timer = None
        self.Bind(wx.EVT_TIMER, self.process_frame)  # bind the method for processing camera frames

        # do a camera scan
        self.btn_update_cam_list(None)

        # object to pass around the raw data matrix bytes without going through the GUI
        self.dmtx_bytes = None

        # database objects
        self.db = DbInterface()
        self.db.connect()

        # Digi-Key API interface
        self.dk_api = DKAPIInterface(auth_complete_callback=self.auth_complete)
        if self.dk_api.auth_valid:
            self.update_auth_status(auth_valid=True)

        # on_close handler
        self.Bind(wx.EVT_CLOSE, self.on_close)

        # resize the grid columns to fit text
        self.grid_results.AutoSizeColumns()
        self.grid_results.SetColSize(6, 200)
        self.grid_results.SetColSize(8, 150)

        # object to keep track of the search results
        self.search_results = None  # should be a list of ItemRecords when populated

        # initialise dialogues
        self.dialog_view_result = ViewResultDialog(parent=self)
        self.dialog_checkout = CheckoutDialog(parent=self)

        # fill in the display area with some entries in the DB
        rows = self.db.get_all()
        self.populate_results(rows=rows)

    def get_fields(self) -> ItemRecord:
        return ItemRecord(
            has_dmtx=True,  # assume to have the dmtx. Better to error out if unknown
            name=self.text_ctrl_name.GetValue(),
            pn=self.text_ctrl_supplier_pn.GetValue(),
            mfg_pn=self.text_ctrl_manufacturer_pn.GetValue(),
            loc=self.text_ctrl_loc.GetValue(),  # compulsory
            qty=self.text_ctrl_qty.GetValue(),  # compulsory
            cat=self.text_ctrl_cat.GetValue(),
            desc=self.text_ctrl_desc.GetValue(),
            supplier=self.text_ctrl_supplier.GetValue(),
            manufacturer=self.text_ctrl_manufacturer.GetValue(),
            proj=self.text_ctrl_prj.GetValue(),
            cust_ref=self.text_ctrl_cust_ref.GetValue(),
            comment=self.text_ctrl_comment.GetValue(),
        )

    def set_fields(self, item: ItemRecord, skip_loc=False) -> None:
        self.text_ctrl_name.SetValue(item.name)
        self.text_ctrl_supplier_pn.SetValue(item.supplier_pn)
        self.text_ctrl_manufacturer_pn.SetValue(item.manufacturer_pn)
        if not skip_loc:
            self.text_ctrl_loc.SetValue(item.location)
        self.text_ctrl_qty.SetValue(str(item.quantity))
        self.text_ctrl_cat.SetValue(item.category)
        self.text_ctrl_desc.SetValue(item.description)
        self.text_ctrl_supplier.SetValue(item.supplier)
        self.text_ctrl_manufacturer.SetValue(item.manufacturer)
        self.text_ctrl_prj.SetValue(item.used_by_proj)
        self.text_ctrl_cust_ref.SetValue(item.customer_ref)
        self.text_ctrl_comment.SetValue(item.comment)

    def btn_update_cam_list(self, event):
        """
        Scans for connected cameras and update the drop-down box in the GUI accordingly.
        :param event: event object from button clicking
        :return: None
        """
        scan_range = 5

        # iterate through the scan range
        index = 0
        devices = [False] * scan_range  # True means a camera is present at the index
        while True:
            cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
            if not cap.read()[0]:  # try to read one frame, failed to read
                devices[index] = False
            else:
                devices[index] = True
            cap.release()
            index += 1
            if index == scan_range:
                break

        # update GUI
        self.choice_camera.Clear()
        if True in devices:  # has at least one camera connected
            for i in range(scan_range):
                if devices[i]:
                    self.choice_camera.Append("{}".format(i))  # add to the combo box
            # set the first camera as selected
            self.choice_camera.SetSelection(0)

    def btn_enable_camera(self, event):
        if self.camera_on is False:  # camera not on, turn it on
            # get camera number from the combo box
            cam_num = self.choice_camera.GetStringSelection()
            if cam_num == "":  # no selection
                if self.choice_camera.IsListEmpty():  # no camera detected or connected
                    self.show_modal_dialog(message="No cameras detected! "
                                                   "If a new camera is connected, are the drivers installed?"
                                                   "Click \"Update Cameras\" to refresh the list",
                                           caption="Error",
                                           style=wx.OK | wx.ICON_ERROR)
                else:  # camera detected but not selected.
                    # This shouldn't happen because the first one is always selected
                    # when the camera list is updated
                    print("This isn't supposed to happen - no camera selected")
            else:  # a camera number is selected, proceed
                self.camera_cap = cv2.VideoCapture(int(cam_num), cv2.CAP_DSHOW)
                # CAP_DSHOW - direct show. Removes this warning:
                # https://stackoverflow.com/questions/59596748/warn0-global-sourcereadercbsourcereadercb-terminating-async-callback-wa
                self.button_camera.SetLabel("Disable Camera")
                self.camera_on = True

                # set up and start the camera feed display
                ret, self.camera_frame = self.camera_cap.read()
                if ret:
                    self.frame_height, self.frame_width = self.camera_frame.shape[:2]
                    self.frame_bmp = wx.Bitmap.FromBuffer(self.frame_width, self.frame_height, self.camera_frame)

                    self.camera_timer = wx.Timer(self)  # used to update the camera view
                    self.camera_timer.Start(1000. / FRAME_RATE)
                else:
                    print("Error no camera image")
        else:  # camera is on, turn it off
            self.camera_timer.Stop()
            self.camera_timer = None
            self.camera_cap.release()
            self.camera_on = False
            self.button_camera.SetLabel("Enable Camera")

    def btn_save(self, event):
        # fetch values from the input fields
        item = self.get_fields()

        if item.location == "":
            self.show_modal_dialog(message="The Location field can't be empty",
                                   caption="Error",
                                   style=wx.OK | wx.ICON_ERROR)
            return  # abort saving and return. Multiple errors hurt UX
        if item.quantity == "":
            self.show_modal_dialog(message="The Quantity field can't be empty",
                                   caption="Error",
                                   style=wx.OK | wx.ICON_ERROR)
            return  # abort saving
        if item.name == "" and item.supplier_pn == "" and item.manufacturer_pn == "":
            self.show_modal_dialog(message="Please input at least one of the name,\n"
                                           "supplier P/N or manufacturer P/N.",
                                   caption="Error",
                                   style=wx.OK | wx.ICON_ERROR)
            return  # abort saving

        if (self.dmtx_bytes is not None) and (self.dmtx_bytes != b""):
            # the item has a data matrix code associated with it
            item.dmtx = self.dmtx_bytes
            item.has_dmtx = True

            # check if it's already in the database
            test_item = self.db.get_item_by_code(item.dmtx)
            if test_item is None:  # not in the DB
                self.db.add_component(item=item)
            else:
                self.db.update_component(item=item)
        else:  # the item doesn't have a data matrix code
            item.has_dmtx = False
            self.db.add_component(item=item)
        self.btn_cancel(event=None)

    def btn_cancel(self, event):
        self.clear_inputs()
        self.button_delete.Disable()
        if self.camera_timer is not None:
            self.camera_timer.Start(1000. / FRAME_RATE)  # resume camera if it was running

    def btn_auth(self, event):
        if self.dk_api.auth_valid:  # no need to authorise
            self.show_modal_dialog(message="Already authorised.",
                                   caption="Info",
                                   style=wx.OK | wx.ICON_INFORMATION)
            self.update_auth_status(auth_valid=True)
        else:
            self.dk_api.authorise()

    def btn_search_basic(self, event):
        keyword = self.text_ctrl_basic_search.GetValue()
        rows = self.db.basic_search(keyword=keyword)
        self.populate_results(rows=rows)

    def btn_search_adv(self, event):
        # collect input field contents
        cols = [0] * 3
        inputs = [""] * 3
        logics = [0] * 2
        cols[0] = self.choice_search_1.GetSelection()
        cols[1] = self.choice_search_2.GetSelection()
        cols[2] = self.choice_search_3.GetSelection()
        inputs[0] = self.text_ctrl_adv_search_1.GetValue()
        inputs[1] = self.text_ctrl_adv_search_2.GetValue()
        inputs[2] = self.text_ctrl_adv_search_3.GetValue()
        logics[0] = self.choice_logic_1.GetSelection()
        logics[1] = self.choice_logic_2.GetSelection()

        # ignore empty and not-selected fields
        ignore = [False] * 3
        for i in range(3):
            if inputs[i] == "" or cols[i] == wx.NOT_FOUND:
                ignore[i] = True

        if ignore == [True, True, True]:
            return  # inputs incomplete, nothing to search

        cols_for_search = []
        inputs_for_search = []
        logics_for_search = []
        # only keep the complete input pairs, to pass onto search
        for i in range(3):
            if not ignore[i]:
                cols_for_search += [self.choice_search_1.GetString(cols[i])]
                inputs_for_search += [inputs[i]]
                if i > 0:
                    logics_for_search += [self.choice_logic_1.GetString(logics[i - 1])]

        rows = self.db.advanced_search(cols=cols_for_search, inputs=inputs_for_search, logics=logics_for_search)
        self.populate_results(rows=rows)

    def btn_clear_adv_search(self, event):
        self.text_ctrl_adv_search_1.SetValue("")
        self.text_ctrl_adv_search_2.SetValue("")
        self.text_ctrl_adv_search_3.SetValue("")

    def btn_view_result(self, event):
        # get info about the selected component
        selected_row = self.grid_results.GetSelectedRows()[0]
        selected_item = self.search_results[selected_row]
        self.dialog_view_result.setup(item_to_show=selected_item, db=self.db)
        self.dialog_view_result.ShowModal()

    def btn_checkout(self, event):
        selected_row = self.grid_results.GetSelectedRows()[0]
        selected_item = self.search_results[selected_row]
        self.dialog_checkout.setup(db=self.db, item=selected_item)
        self.dialog_checkout.ShowModal()

    def btn_delete(self, event):
        dlg = wx.MessageDialog(parent=self,
                               message="Are you sure?",
                               caption="Confirmation",
                               style=wx.YES_NO | wx.NO_DEFAULT | wx.CANCEL | wx.ICON_WARNING)
        res = dlg.ShowModal()
        if res == wx.ID_YES:  # confirm to delete
            self.db.remove_component(dmtx=self.dmtx_bytes)
            self.btn_cancel(event=None)
            print("Deleted item.")

    def btn_edit(self, event):
        selected_row = self.grid_results.GetSelectedRows()[0]
        selected_item: ItemRecord = self.search_results[selected_row]
        self.set_fields(item=selected_item)
        self.dmtx_bytes = selected_item.dmtx
        self.check_deletable()

        self.notebook_main.SetSelection(page=0)  # switch to the scan/edit tab

    def check_deletable(self):
        enable_delete = False
        if self.dmtx_bytes is None or self.dmtx_bytes == b"":
            enable_delete = False

        res = self.db.get_item_by_code(dmtx=self.dmtx_bytes)
        if res is not None:
            enable_delete = True
        else:
            enable_delete = False

        if enable_delete:
            self.button_delete.Enable()
        else:
            self.button_delete.Disable()

    def results_row_selected(self, event):
        # enable the buttons
        self.button_view.Enable()
        self.button_checkout.Enable()
        self.button_checkin.Enable()
        self.button_edit.Enable()

        event.Skip()  # pass on the event to update GUI

    def results_cell_selected(self, event):
        # This function makes sure there's only one row selected in the Grid.
        # Note that the display may highlight multiple rows anyway
        selected_rows = self.grid_results.GetSelectedRows()
        if len(selected_rows) > 1:
            self.grid_results.ClearSelection()
            self.grid_results.SelectRow(row=selected_rows[-1])  # pick the last one in the selected rows

    def populate_results(self, rows: list):
        # when this function is called, the row selection is lost.
        # Therefore, disable the buttons that need a row selected
        self.button_view.Disable()
        self.button_checkout.Disable()
        self.button_checkin.Disable()
        self.button_edit.Disable()

        self.search_results = rows

        row_count = self.grid_results.GetNumberRows()
        new_row_count = len(rows)
        if row_count > 0:
            self.grid_results.DeleteRows(numRows=row_count)
        self.grid_results.InsertRows(numRows=new_row_count)
        for i in range(new_row_count):
            item: ItemRecord = rows[i]
            self.grid_results.SetCellValue(i, 0, str(item.name))
            self.grid_results.SetCellValue(i, 1, str(item.supplier_pn))
            self.grid_results.SetCellValue(i, 2, str(item.manufacturer_pn))
            self.grid_results.SetCellValue(i, 3, str(item.location))
            self.grid_results.SetCellValue(i, 4, str(item.quantity))
            self.grid_results.SetCellValue(i, 5, str(item.category))
            self.grid_results.SetCellValue(i, 6, str(item.description))
            self.grid_results.SetCellValue(i, 7, str(item.supplier))
            self.grid_results.SetCellValue(i, 8, str(item.manufacturer))
            self.grid_results.SetCellValue(i, 9, str(item.used_by_proj))
            self.grid_results.SetCellValue(i, 10, str(item.customer_ref))
            self.grid_results.SetCellValue(i, 11, str(item.comment))

    def radiobox_decode_handler(self, event):
        user_selection = self.radio_box_decode.GetSelection()
        if user_selection == 0:  # local
            # disable displays and controls for the Digi-Key auth
            self.label_auth_status_label.Disable()
            self.label_auth_status.Disable()
            self.button_auth.Disable()

        elif user_selection == 1:  # web
            # enable displays and controls for the Digi-Key auth
            self.label_auth_status_label.Enable()
            self.label_auth_status.Enable()
            self.button_auth.Enable()

    def auth_complete(self):  # callback function that gets called from dkinterface
        self.update_auth_status(auth_valid=self.dk_api.auth_valid)

    def update_auth_status(self, auth_valid=False):
        if auth_valid:
            self.label_auth_status.SetBackgroundColour(wx.Colour(127, 255, 127))  # change indicator to green
        else:
            self.label_auth_status.SetBackgroundColour(wx.Colour(255, 127, 127))  # change indicator to red
        self.Refresh()

    def show_modal_dialog(self, *args, **kwargs):  # just to make showing a dialog a bit shorter in code
        dialog = wx.MessageDialog(self, *args, **kwargs)
        dialog.ShowModal()
        dialog.Destroy()  # may not need

    def process_frame(self, event):
        ret, self.camera_frame = self.camera_cap.read()
        if ret:
            # do some conditioning magic:
            # convert to grayscale. This seems to work the best compared to coloured and black & white
            gray = cv2.cvtColor(self.camera_frame, cv2.COLOR_BGR2GRAY)

            data_raw = decode(gray, timeout=50, max_count=1)  # 50ms timeout
            if len(data_raw) > 0:  # got a string
                self.camera_timer.Stop()  # stop camera frame acquisition and display
                if platform.system() == "Windows":
                    winsound.Beep(2500, 200)  # short beep
                self.dmtx_bytes = data_raw[0].data
                print("Success!")
                print(self.dmtx_bytes)

                # check if the code is present in the DB
                item: ItemRecord = self.db.get_item_by_code(dmtx=self.dmtx_bytes)
                if item is not None:  # the item is present in the DB
                    print("Item is present in the DB")
                    self.set_fields(item=item)
                    self.check_deletable()
                else:
                    # find info without the DigiKey API in local mode
                    if self.radio_box_decode.GetSelection() == 0:
                        mfg_pn_start = self.dmtx_bytes.find(b"\x1d1P")  # manufacturer's P/N begins with this sequence
                        mfg_pn_end = self.dmtx_bytes.find(b"\x1d", mfg_pn_start + 1)
                        mfg_pn = str(self.dmtx_bytes[mfg_pn_start + 3: mfg_pn_end])  # skip the \x1d1P
                        mfg_pn = mfg_pn[2:-1]  # trim out the b'' from bytes to str conversion

                        qty_start = self.dmtx_bytes.find(b"\x1dQ")  # quantity
                        qty_end = self.dmtx_bytes.find(b"\x1d", qty_start + 1)  # same as above
                        qty = str(self.dmtx_bytes[qty_start + 2: qty_end])
                        qty = qty[2:-1]

                        # fill in the GUI fields
                        self.text_ctrl_manufacturer_pn.SetLabel(mfg_pn)
                        self.text_ctrl_qty.SetLabel(qty)

                    if self.radio_box_decode.GetSelection() == 1:  # using Digi-Key API
                        self.get_component_info_web(dmtx_bytes=self.dmtx_bytes)

                # flush the camera frames a bit
                for i in range(20):
                    self.camera_cap.read()

            self.redraw_camera(gray_frame=gray)
        else:
            print("Failed to read the camera frame...")

    def redraw_camera(self, gray_frame):
        self.camera_frame = np.stack((gray_frame,) * 3, axis=-1)  # convert grayscale image to RGB format to display

        try:
            self.frame_bmp.CopyFromBuffer(self.camera_frame)
        except ValueError:
            print(self.camera_frame)
            raise
        self.bitmap_camera.SetBitmap(self.frame_bmp)

    def get_component_info_web(self, dmtx_bytes: bytes):
        """
        Retrieves component details using Digi-Key's API
        :param dmtx_bytes: original data from the data matrix code
        :return: the component information in a dictionary
        """
        api_success, barcode2d_resp = self.dk_api.product_2d_barcode(dmtx_bytes=dmtx_bytes)

        if api_success:  # OK
            resp_json = barcode2d_resp.json()

            # fill in the GUI
            desc = resp_json["ProductDescription"]
            item = ItemRecord(
                has_dmtx=True,
                pn=resp_json["DigiKeyPartNumber"],
                desc=desc,
                mfg_pn=resp_json["ManufacturerPartNumber"],
                # take the first word in the description as the category; this will work in most cases
                cat=desc.split()[0],
                manufacturer=resp_json["ManufacturerName"],
                qty=resp_json["Quantity"],
                comment="Sales Order ID: {}".format(resp_json["SalesorderId"])
            )

            # check if customer reference is present
            # customer reference if present, otherwise Digi-Key part number
            cust_ref_start = self.dmtx_bytes.find(b"\x1dP")
            cust_ref_end = self.dmtx_bytes.find(b"\x1d", cust_ref_start + 1)
            cust_ref = str(self.dmtx_bytes[cust_ref_start + 2: cust_ref_end])
            cust_ref = cust_ref[2:-1]  # trim out the b'' characters
            if cust_ref != item.supplier_pn:  # customer reference is present
                item.customer_ref = cust_ref

            # fill in the supplier field as Digi-Key
            item.supplier = "Digi-Key"

            self.set_fields(item=item, skip_loc=True)

            print("Full response:")
            print(resp_json)
        else:
            print("Error occurred when fetching decoding results! Full response:")
            print(barcode2d_resp.text)
            self.show_modal_dialog(message="Failed to retrieve component information from Digi-Key!\n"
                                           "If you're scanning a Mouser bag, try local decode mode.",
                                   caption="Error",
                                   style=wx.OK | wx.ICON_ERROR)
            self.btn_cancel(None)

    def clear_inputs(self):
        """
        Clears all input fields except location. Also clears the data matrix object
        :return:
        """
        self.text_ctrl_name.SetLabel("")
        self.text_ctrl_qty.SetLabel("")
        self.text_ctrl_supplier_pn.SetLabel("")
        self.text_ctrl_manufacturer_pn.SetLabel("")
        self.text_ctrl_cat.SetLabel("")
        self.text_ctrl_manufacturer.SetLabel("")
        self.text_ctrl_supplier.SetLabel("")
        self.text_ctrl_prj.SetLabel("")
        self.text_ctrl_desc.SetLabel("")
        self.text_ctrl_cust_ref.SetLabel("")
        self.text_ctrl_comment.SetLabel("")
        self.dmtx_bytes = None

    def main_notebook_changed(self, event):
        # clear te search results object as it won't make sense outside the search/view tab
        self.search_results = None

        if self.notebook_main.GetSelection() == 1:  # switched to search tab
            # resize the columns to fit window
            grid_width = self.grid_results.GetSize().GetWidth()
            cols_width = 0
            for i in range(11):  # sum up the total width of all the columns except the last one
                cols_width += self.grid_results.GetColSize(i)

            # calculate the resize target for the last column
            new_width = grid_width - cols_width - 84
            if new_width > 130:
                self.grid_results.SetColSize(11, new_width)

    def on_close(self, event):
        # clean up the Digi-Key API
        if self.dk_api.httpd is not None:
            self.dk_api.httpd.shutdown()  # stop the server
            self.dk_api.httpd.close()  # close the TCP socket

        # release the database
        self.db.close()

        # stop the camera
        if self.camera_on:
            self.camera_timer.Stop()
            self.camera_cap.release()
            self.camera_on = False
        event.Skip()  # pass on to the default window close handler


class InventoryApp(wx.App):
    def OnInit(self):
        self.frame = InventoryFrame(None, wx.ID_ANY, "")
        self.SetTopWindow(self.frame)
        self.frame.Show()
        return True


if __name__ == "__main__":
    inv_app = InventoryApp()
    inv_app.MainLoop()
