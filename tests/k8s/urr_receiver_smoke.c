#include <signal.h>
#include <unistd.h>
#include "urr_receiver.h"
static volatile sig_atomic_t stop;
static void on_stop(int sig) {(void)sig;stop=1;}
int main(void) {
  signal(SIGTERM,on_stop);signal(SIGINT,on_stop);
  if(urr_receiver_start()!=0)return 2;
  while(!stop)sleep(1);
  urr_receiver_stop();return 0;
}
