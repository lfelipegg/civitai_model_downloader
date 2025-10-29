    def _safe_update_status(self, task_id, status_text, text_color=None):
        """Safely update task status with error handling"""
        try:
            task = self.download_tasks.get(task_id)
            if not task:
                return

            status_label = task.get('status_label')
            status_indicator = task.get('status_indicator')

            if status_label is not None:
                if text_color:
                    status_label.configure(text=status_text, text_color=text_color)
                else:
                    status_label.configure(text=status_text)
            else:
                return

            if status_indicator is not None:
                indicator_color = self._get_status_indicator_color(status_text)
                try:
                    status_indicator.configure(fg_color=indicator_color)
                except Exception:
                    status_indicator.configure(text_color=indicator_color)
        except Exception as e:
            print(f"Error updating status for task {task_id}: {e}")
                    try:
                        status_indicator.configure(fg_color=indicator_color)
                    except Exception:
                        pass
        except Exception as e:
            print(f"Error updating status for task {task_id}: {e}")
    
    def _get_status_indicator_color(self, status_text):
        """Get appropriate color for status indicator based on status text"""
        status_lower = status_text.lower()
        
        if "complete" in status_lower or "downloaded" in status_lower:
            return "#4CAF50"  # Green for success
        elif "failed" in status_lower or "error" in status_lower or "cancelled" in status_lower:
            return "#f44336"  # Red for errors
        elif "downloading" in status_lower:
            return "#2196F3"  # Blue for active
        elif "paused" in status_lower:
            return "#9E9E9E"  # Gray for paused
        elif "fetching" in status_lower or "connecting" in status_lower:
            return "#ffff00"  # Yellow for connecting
        else:
            return "#ffa500"  # Orange for initializing/unknown
    
    # Note: _update_task_progress_ui method is now replaced by _apply_progress_update
    # which is called via the progress queue system for better performance
 
    def _on_closing(self):
        if messagebox.askokcancel("Quit", "Do you want to quit? Ongoing downloads will be interrupted."):
            self.stop_event.set() # Signal main queue processing thread to stop
            self.log_message("Shutdown initiated. Signalling individual downloads to stop...")
            
            # Stop progress processor first
            try:
                self.progress_queue.put_nowait(None)  # Poison pill to stop progress processor
            except (queue.Full, AttributeError):
                pass
            
            # Signal all individual download threads to stop and clear pause events
            active_tasks = list(self.download_tasks.items())  # Iterate over a copy as dict might change
            for task_id, task_data in active_tasks:
                try:
                    if 'stop_event' in task_data and hasattr(task_data['stop_event'], 'set'):
                        task_data['stop_event'].set()
                    if 'pause_event' in task_data and hasattr(task_data['pause_event'], 'clear'):
                        task_data['pause_event'].clear()  # Clear pause event to unblock any waiting threads
                    
                    # Update UI elements safely
                    if task_data.get('cancel_button'):
                        try:
                            task_data['cancel_button'].configure(state="disabled", text="Stopping...")
                        except:
                            pass
                    if task_data.get('pause_button'):
                        try:
                            task_data['pause_button'].configure(state="disabled")
                        except:
                            pass
                    if task_data.get('resume_button'):
                        try:
                            task_data['resume_button'].configure(state="disabled")
                        except:
                            pass
                except Exception as e:
                    print(f"Error stopping task {task_id}: {e}")

            self.log_message("Waiting for threads to finish...")
            
            # Collect all threads that need to be waited for
            threads_to_wait = []
            
            # Progress processor thread
            if hasattr(self, 'progress_thread') and self.progress_thread.is_alive():
                threads_to_wait.append(('progress_thread', self.progress_thread, 2))
            
            # Queue processor thread
            if hasattr(self, 'queue_processor_thread') and self.queue_processor_thread.is_alive():
                threads_to_wait.append(('queue_processor_thread', self.queue_processor_thread, 5))
            
            # Completion watcher thread
            if hasattr(self, 'completion_watcher_thread') and self.completion_watcher_thread.is_alive():
                threads_to_wait.append(('completion_watcher_thread', self.completion_watcher_thread, 3))
            
            # Processing and completion thread
            if hasattr(self, 'processing_and_completion_thread') and self.processing_and_completion_thread.is_alive():
                threads_to_wait.append(('processing_and_completion_thread', self.processing_and_completion_thread, 3))
            
            # Wait for all background threads with proper timeouts
            background_threads_copy = dict(self.background_threads)  # Create copy to avoid modification during iteration
            for task_id, bg_thread in background_threads_copy.items():
                if bg_thread and bg_thread.is_alive():
                    threads_to_wait.append((f'background_thread_{task_id}', bg_thread, 2))
            
            # Wait for each thread with individual timeouts
            total_wait_start = time.time()
            for thread_name, thread, timeout in threads_to_wait:
                if time.time() - total_wait_start > 15:  # Total timeout of 15 seconds
                    self.log_message("Thread cleanup timeout exceeded, forcing shutdown...")
                    break
                    
                try:
                    thread.join(timeout=timeout)
                    if thread.is_alive():
                        self.log_message(f"{thread_name} did not terminate gracefully within {timeout}s.")
                    else:
                        self.log_message(f"{thread_name} terminated successfully.")
                except Exception as e:
                    self.log_message(f"Error waiting for {thread_name}: {e}")
            
            # Clear all thread references
            self.background_threads.clear()
            
            # Clean up progress manager resources
            try:
                if hasattr(self, 'download_tasks'):
                    for task_id in list(self.download_tasks.keys()):
                        try:
                            from src.progress_tracker import progress_manager
                            progress_manager.remove_tracker(task_id)
                        except:
                            pass
            except:
                pass
            
            # Stop memory monitoring
            try:
                memory_monitor.stop_monitoring()
                self.log_message("Memory monitoring stopped.")
            except:
                pass
            
            # Thumbnail cache cleanup skipped (feature disabled).
            
            self.log_message("Thread cleanup completed. Closing application...")
            self.destroy() # Close the main window
    def clear_gui(self):
        self.url_entry.delete("1.0", ctk.END)
        # Only clear the URL entry as requested

        # Clear background threads tracking
        self.background_threads.clear()

        self.log_message("URL input cleared.")
        # Do not reset other fields or download queue display
        # As per the new requirement, "Clear GUI" only clears the current URLs.

if __name__ == "__main__":
    app = App()
    app.mainloop()